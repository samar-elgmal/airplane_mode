"""Small builders for test records. Every call creates fresh, uniquely named records."""
import frappe
from frappe.utils import add_days, today


def unique(prefix):
	return f"{prefix}-{frappe.generate_hash(length=6)}"


def make_airport(code=None):
	code = code or frappe.generate_hash(length=3).upper()
	doc = frappe.get_doc({"doctype": "Airport", "code": code, "city": "Test City", "country": "Testland"})
	doc.name = unique(f"Test Airport {code}")  # Airport uses Prompt naming
	return doc.insert()


def make_crew_member(role="Pilot"):
	return frappe.get_doc({"doctype": "Crew Member", "full_name": unique("Crew"), "crew_role": role}).insert()


def make_flight(capacity=20, submit=False, gate_number=None):
	airline = frappe.get_doc({"doctype": "Airline", "customer_care_number": "100", "headquarters": "Cairo"})
	airline.name = unique("Test Airline")  # Airline uses Prompt naming
	airline.insert()
	airplane = frappe.get_doc(
		{"doctype": "Airplane", "model": "A320", "airline": airline.name, "capacity": capacity}
	).insert()
	flight = frappe.get_doc(
		{
			"doctype": "Airplane Flight",
			"airplane": airplane.name,
			"date_of_departure": add_days(today(), 7),
			"time_of_departure": "10:00:00",
			"duration": 7200,
			"source_airport": make_airport().name,
			"destination_airport": make_airport().name,
			"gate_number": gate_number,
		}
	).insert()
	if submit:
		flight.submit()
	return flight


def make_ticket(flight, submit=False):
	passenger = frappe.get_doc(
		{"doctype": "Flight Passenger", "first_name": unique("Pax"), "date_of_birth": "1990-01-01"}
	).insert()
	ticket = frappe.get_doc(
		{
			"doctype": "Airplane Ticket",
			"passenger": passenger.name,
			"flight": flight.name,
			"flight_price": 100,
			"status": "Boarded" if submit else "Booked",
		}
	).insert()
	if submit:
		ticket.submit()
	return ticket
