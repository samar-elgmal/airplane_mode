# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.query_builder.functions import Sum


def execute(filters=None):
	columns = get_columns()
	data = get_data()

	total_revenue = sum(row["revenue"] for row in data)

	chart = {
		"data": {
			"labels": [row["airline"] for row in data],
			"datasets": [{"values": [row["revenue"] for row in data]}],
		},
		"type": "donut",
	}

	report_summary = [
		{
			"value": total_revenue,
			"indicator": "Green",
			"label": _("Total Revenue"),
			"datatype": "Currency",
		}
	]

	return columns, data, None, chart, report_summary


def get_columns():
	return [
		{
			"fieldname": "airline",
			"label": _("Airline"),
			"fieldtype": "Link",
			"options": "Airline",
			"width": 200,
		},
		{
			"fieldname": "revenue",
			"label": _("Revenue"),
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data():
	revenue_by_airline = get_revenue_by_airline()

	# Start from every airline so airlines without sales show 0
	airlines = frappe.get_all("Airline", pluck="name")
	data = [
		{"airline": airline, "revenue": revenue_by_airline.get(airline, 0)}
		for airline in airlines
	]
	data.sort(key=lambda row: row["revenue"], reverse=True)
	return data


def get_revenue_by_airline():
	"""Sum of submitted ticket amounts per airline: Ticket -> Flight -> Airplane -> Airline."""
	ticket = frappe.qb.DocType("Airplane Ticket")
	flight = frappe.qb.DocType("Airplane Flight")
	airplane = frappe.qb.DocType("Airplane")

	rows = (
		frappe.qb.from_(ticket)
		.join(flight).on(ticket.flight == flight.name)
		.join(airplane).on(flight.airplane == airplane.name)
		.select(airplane.airline, Sum(ticket.total_amount).as_("revenue"))
		.where(ticket.docstatus == 1)
		.groupby(airplane.airline)
		.run(as_dict=True)
	)
	# print(query.get_sql())

	# 	SELECT `tabAirplane`.`airline`, SUM(`tabAirplane Ticket`.`total_amount`) AS `revenue`
	# FROM `tabAirplane Ticket`
	# JOIN `tabAirplane Flight` ON `tabAirplane Ticket`.`flight` = `tabAirplane Flight`.`name`
	# JOIN `tabAirplane` ON `tabAirplane Flight`.`airplane` = `tabAirplane`.`name`
	# WHERE `tabAirplane Ticket`.`docstatus` = 1
	# GROUP BY `tabAirplane`.`airline`

	# rows = [
    # {"airline": "EgyptAir", "revenue": 3387.0},
    # {"airline": "IndiGo",   "revenue": 1145.0},
    # {"airline": "AirAsia",  "revenue": 1068.0},
	# ]
	# i want return like {"EgyptAir": 3387.0, "IndiGo": 1145.0, "AirAsia": 1068.0}

	# result = {}
	# for row in rows:                               # for row in rows
	# 	result[row.airline] = row.revenue or 0     # row.airline: row.revenue or 0
	# return result



	return {row.airline: row.revenue or 0 for row in rows}
