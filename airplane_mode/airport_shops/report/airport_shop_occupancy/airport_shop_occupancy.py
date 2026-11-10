# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	columns = [
		{"fieldname": "airport", "label": _("Airport"), "fieldtype": "Link", "options": "Airport", "width": 220},
		{"fieldname": "total", "label": _("Total Shops"), "fieldtype": "Int", "width": 120},
		{"fieldname": "available", "label": _("Available"), "fieldtype": "Int", "width": 120},
		{"fieldname": "occupied", "label": _("Occupied"), "fieldtype": "Int", "width": 120},
		{"fieldname": "occupancy", "label": _("Occupancy %"), "fieldtype": "Percent", "width": 120},
	]

	condition = "where airport = %(airport)s" if filters.get("airport") else ""
	# Always computed live from the shops; never reads the stored counts on Airport.
	data = frappe.db.sql(
		f"""select airport,
			count(*) as total,
			sum(status = 'Available') as available,
			sum(status = 'Occupied') as occupied
		from `tabAirport Shop` {condition}
		group by airport order by airport""",
		filters,
		as_dict=True,
	)
	for row in data:
		row.available, row.occupied = int(row.available or 0), int(row.occupied or 0)
		row.occupancy = flt(row.occupied * 100 / row.total, 1) if row.total else 0

	chart = {
		"data": {
			"labels": [row.airport for row in data],
			"datasets": [
				{"name": _("Available"), "values": [row.available for row in data]},
				{"name": _("Occupied"), "values": [row.occupied for row in data]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}
	return columns, data, None, chart
