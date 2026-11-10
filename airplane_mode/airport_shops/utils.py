import frappe
from frappe.utils import add_days, add_months, date_diff, flt, getdate


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
