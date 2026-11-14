import frappe
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import add_days, add_months, date_diff, flt, getdate, today


def update_airport_shop_counts(airport):
	"""Recompute the stored shop counts on an Airport from the Airport Shop table."""
	if not airport or not frappe.db.exists("Airport", airport):
		return
	total = frappe.db.count("Airport Shop", {"airport": airport})
	occupied = frappe.db.count("Airport Shop", {"airport": airport, "status": "Occupied"})
	frappe.db.set_value(
		"Airport",
		airport,
		{"total_shops": total, "occupied_shops": occupied, "available_shops": total - occupied},
		update_modified=False,
	)


def get_anniversary_date(start_date, months):
	"""start_date + N months, always computed from the ORIGINAL start date.

	add_months uses relativedelta, which clamps to the month's last day without drifting:
	31 Jan -> 28 Feb -> 31 Mar (not 28 Mar).
	"""
	return getdate(add_months(getdate(start_date), months))


def build_rent_schedule(start_date, end_date, rent_amount, precision=2):
	"""Split [start_date, end_date] (both inclusive) into anniversary periods.

	Each period runs from one anniversary to the day before the next. Full periods cost
	rent_amount. A last period cut short by end_date is prorated by days against the
	length of the full period it belongs to.
	"""
	start, end = getdate(start_date), getdate(end_date)
	rows = []
	n = 0
	while True:
		period_start = get_anniversary_date(start, n)
		if period_start > end:
			break
		full_period_end = getdate(add_days(get_anniversary_date(start, n + 1), -1))
		period_end = min(full_period_end, end)
		if period_end == full_period_end:
			amount = flt(rent_amount, precision)
		else:
			days = date_diff(period_end, period_start) + 1
			full_days = date_diff(full_period_end, period_start) + 1
			amount = flt(flt(rent_amount) * days / full_days, precision)
		rows.append(
			frappe._dict(
				period_start=period_start,
				period_end=period_end,
				due_date=period_start,
				amount=amount,
				paid_amount=0,
				outstanding_amount=amount,
				status="Unpaid",
			)
		)
		n += 1
	return rows


def get_active_contract(shop, on_date=None):
	"""The submitted contract covering on_date (default today), or None.

	The overlap rule guarantees there is at most one.
	"""
	day = getdate(on_date or today())
	rows = frappe.get_all(
		"Shop Contract",
		filters={"shop": shop, "docstatus": 1, "start_date": ["<=", day], "end_date": [">=", day]},
		fields=["name", "tenant", "end_date"],
		order_by="start_date desc",
		limit=1,
	)
	return rows[0] if rows else None


def sync_shop_status(shop, on_date=None):
	"""Single source of truth for a shop's status. Recomputed from ALL submitted contracts.

	Returns True when it wrote changes to the shop, so callers holding the doc can reload it.
	"""
	current = frappe.db.get_value(
		"Airport Shop",
		shop,
		["airport", "status", "current_tenant", "current_contract", "contract_expiry"],
		as_dict=True,
	)
	if not current:
		return False
	contract = get_active_contract(shop, on_date)
	if contract:
		target = {
			"status": "Occupied",
			"current_tenant": contract.tenant,
			"current_contract": contract.name,
			"contract_expiry": getdate(contract.end_date),
		}
	else:
		target = {"status": "Available", "current_tenant": None, "current_contract": None, "contract_expiry": None}

	changed = any((current.get(key) or None) != (value or None) for key, value in target.items())
	if changed:
		# set_value skips Airport Shop.validate, which blocks everyone else from these fields.
		frappe.db.set_value("Airport Shop", shop, target)
	update_airport_shop_counts(current.airport)
	return changed


def update_contract_totals(contract):
	"""Recompute a contract's totals from its schedule rows.

	Callers hold the contract row lock. The read is a locking read (FOR UPDATE) because under
	REPEATABLE READ a plain SELECT would reuse an older snapshot and miss another period's
	payment committed while we waited for that lock.
	"""
	precision = frappe.get_precision("Shop Contract", "total_amount") or 2
	# total, paid = frappe.db.sql(
	# 	"""select coalesce(sum(amount), 0), coalesce(sum(paid_amount), 0)
	# 	from `tabRent Schedule` where parent = %s and parenttype = 'Shop Contract'
	# 	for update""",
	# 	contract,
	# )[0]
	schedule = frappe.qb.DocType("Rent Schedule")
	total, paid = (
		frappe.qb.from_(schedule)
		.select(Coalesce(Sum(schedule.amount), 0), Coalesce(Sum(schedule.paid_amount), 0))
		.where((schedule.parent == contract) & (schedule.parenttype == "Shop Contract"))
		.for_update()
	).run()[0]
	frappe.db.set_value(
		"Shop Contract",
		contract,
		{
			"total_amount": flt(total, precision),
			"total_paid": flt(paid, precision),
			"total_outstanding": flt(flt(total) - flt(paid), precision),
		},
		update_modified=False,
	)
