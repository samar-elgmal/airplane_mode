import re

import frappe

from airplane_mode.airplane_mode.doctype.airplane_ticket.airplane_ticket import generate_seat

# A valid seat is a number followed by a letter from A to E, e.g. 21A
VALID_SEAT = re.compile(r"^\d+[A-E]$")


def execute():
	"""Give a random seat to old tickets that have no seat or a badly formatted one."""
	tickets = frappe.get_all("Airplane Ticket", fields=["name", "seat"])

	for ticket in tickets:
		if ticket.seat and VALID_SEAT.match(ticket.seat):
			continue
		# db.set_value works on submitted tickets too, and keeps their modified date.
		frappe.db.set_value("Airplane Ticket", ticket.name, "seat", generate_seat(), update_modified=False)
