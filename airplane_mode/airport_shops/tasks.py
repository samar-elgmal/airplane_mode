import frappe
from frappe import _
from frappe.utils import add_days, cint, fmt_money, formatdate, getdate, today

from airplane_mode.airport_shops.utils import sync_shop_status

REMINDER_KINDS = {
	"upcoming": {
		"flag": "reminder_sent_on",
		"link": "reminder_email",
		"template": "rent_reminder",
		"subject": "Rent due on {due_date}: {shop_name}",
	},
	"overdue": {
		"flag": "overdue_reminder_sent_on",
		"link": "overdue_reminder_email",
		"template": "rent_overdue",
		"subject": "Rent overdue since {due_date}: {shop_name}",
	},
}


class ReminderNotQueued(frappe.ValidationError):
	pass


def sync_all_shop_statuses(on_date=None):
	"""Daily: activate contracts that start today, release expired ones, switch back-to-back ones."""
	for shop in frappe.get_all("Airport Shop", pluck="name"):
		sync_shop_status(shop, on_date)


def send_rent_reminders(on_date=None):
	"""Daily: one upcoming and one overdue reminder per unpaid period, at most.

	Returns {"upcoming": n, "overdue": m} (rows actually queued). The scheduler commits at the end.
	"""
	result = {"upcoming": 0, "overdue": 0}
	settings = frappe.get_single("Airport Shop Settings")
	if not settings.enable_rent_reminders:
		return result

	day = getdate(on_date or today())
	windows = {
		# due_date - days_before <= day <= due_date
		"upcoming": (
			"rs.due_date between %(day)s and %(until)s",
			{"until": add_days(day, cint(settings.reminder_days_before))},
		),
		# day >= due_date + overdue_after_days
		"overdue": (
			"rs.due_date <= %(until)s",
			{"until": add_days(day, -max(cint(settings.overdue_after_days), 1))},
		),
	}
	for kind, (condition, values) in windows.items():
		for candidate in _candidates(REMINDER_KINDS[kind]["flag"], condition, {"day": day, **values}):
			if _send_one(candidate.name, candidate.contract, kind, day):
				result[kind] += 1
	return result


def _candidates(flag, condition, values):
	return frappe.db.sql(
		f"""select rs.name, rs.parent as contract
		from `tabRent Schedule` rs
		join `tabShop Contract` sc on sc.name = rs.parent
		where rs.parenttype = 'Shop Contract' and sc.docstatus = 1
			and rs.status != 'Paid' and rs.`{flag}` is null and {condition}
		order by rs.due_date, rs.name""",
		values,
		as_dict=True,
	)


def _send_one(row_name, contract, kind, day):
	"""Queue one reminder inside its own savepoint. True if it was queued and flagged."""
	spec = REMINDER_KINDS[kind]
	save_point = f"rent_reminder_{frappe.generate_hash(length=10)}"
	frappe.db.savepoint(save_point)
	try:
		locked = frappe.db.sql(
			f"""select `{spec['flag']}` as flag, status, period_start, period_end, due_date, outstanding_amount
			from `tabRent Schedule` where name = %s for update""",
			row_name,
			as_dict=True,
		)
		if not locked or locked[0].flag or locked[0].status == "Paid":
			return False  # another run got here first, or it was paid meanwhile
		row = locked[0]

		info = frappe.db.get_value(
			"Shop Contract", contract, ["shop", "tenant", "tenant_email", "airport"], as_dict=True
		)
		args = {
			"tenant_name": frappe.db.get_value("Tenant", info.tenant, "tenant_name"),
			"shop": info.shop,
			"shop_name": frappe.db.get_value("Airport Shop", info.shop, "shop_name"),
			"airport": info.airport,
			"period_start": formatdate(row.period_start),
			"period_end": formatdate(row.period_end),
			"due_date": formatdate(row.due_date),
			"outstanding": fmt_money(row.outstanding_amount, currency=frappe.db.get_default("currency")),
			"contract": contract,
		}
		queued = frappe.sendmail(
			recipients=[info.tenant_email] if info.tenant_email else [],
			subject=spec["subject"].format(**args),
			template=spec["template"],
			args=args,
			reference_doctype="Shop Contract",
			reference_name=contract,
		)
		if not queued:
			# v15 returns [] when every recipient was filtered out (e.g. unsubscribed).
			raise ReminderNotQueued(_("No email was queued for {0}").format(info.tenant_email))

		frappe.db.set_value(
			"Rent Schedule", row_name, {spec["flag"]: day, spec["link"]: queued.name}, update_modified=False
		)
		return True
	except Exception:
		# Undo this row only: the flag and its Email Queue row go together or not at all.
		frappe.db.rollback(save_point=save_point)
		frappe.log_error(title=f"Rent reminder ({kind}) failed for {row_name}")
		return False
