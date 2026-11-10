import frappe


def update_ticket_gate_numbers(flight):
	"""Copy the flight's *current* gate onto all its non-cancelled tickets.

	The gate is read from the DB (not passed in), so running this twice, or after two quick
	gate changes, always leaves tickets on the latest gate. Returns how many tickets changed.
	"""
	gate = frappe.db.get_value("Airplane Flight", flight, "gate_number")
	tickets = frappe.get_all(
		"Airplane Ticket",
		filters={"flight": flight, "docstatus": ["<", 2]},
		fields=["name", "gate_number"],
	)
	changed = 0
	for ticket in tickets:
		if (ticket.gate_number or "") != (gate or ""):
			# set_value skips validation, so submitted tickets can be updated too.
			frappe.db.set_value("Airplane Ticket", ticket.name, "gate_number", gate)
			changed += 1
	return changed
