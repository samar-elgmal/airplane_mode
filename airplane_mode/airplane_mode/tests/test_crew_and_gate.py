from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airplane_mode.tasks import update_ticket_gate_numbers
from airplane_mode.airplane_mode.tests.factories import make_crew_member, make_flight, make_ticket


class TestFlightCrew(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_duplicate_crew_member_is_rejected(self):
		flight = make_flight()
		pilot = make_crew_member("Pilot")
		flight.append("crew", {"crew_member": pilot.name})
		flight.append("crew", {"crew_member": pilot.name})
		with self.assertRaises(frappe.ValidationError):
			flight.save()

	def test_crew_role_comes_from_crew_member(self):
		flight = make_flight()
		pilot = make_crew_member("Pilot")
		flight.append("crew", {"crew_member": pilot.name, "crew_role": "Cabin Crew"})  # tampered value
		flight.save()
		self.assertEqual(flight.crew[0].crew_role, "Pilot")


GATE_JOB = "airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers"


def gate_job_calls(mock_enqueue):
	return [c for c in mock_enqueue.call_args_list if c.args and c.args[0] == GATE_JOB]


class TestGateNumber(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_new_ticket_gets_flight_gate(self):
		flight = make_flight(gate_number="A1")
		self.assertEqual(make_ticket(flight).gate_number, "A1")

	def test_job_updates_draft_and_submitted_tickets(self):
		flight = make_flight(gate_number="A1")
		draft, submitted = make_ticket(flight), make_ticket(flight, submit=True)
		frappe.db.set_value("Airplane Flight", flight.name, "gate_number", "B7")

		update_ticket_gate_numbers(flight.name)

		self.assertEqual(frappe.db.get_value("Airplane Ticket", draft.name, "gate_number"), "B7")
		self.assertEqual(frappe.db.get_value("Airplane Ticket", submitted.name, "gate_number"), "B7")

	def test_job_reads_current_gate_and_is_idempotent(self):
		flight = make_flight(gate_number="A1")
		ticket = make_ticket(flight)
		frappe.db.set_value("Airplane Flight", flight.name, "gate_number", "C3")

		self.assertEqual(update_ticket_gate_numbers(flight.name), 1)
		self.assertEqual(update_ticket_gate_numbers(flight.name), 0)  # second run changes nothing
		self.assertEqual(frappe.db.get_value("Airplane Ticket", ticket.name, "gate_number"), "C3")

	def test_gate_change_after_submit_enqueues_exactly_one_job(self):
		flight = make_flight(gate_number="A1", submit=True)
		flight.reload()
		with patch("frappe.enqueue") as enqueue:
			flight.gate_number = "D4"
			flight.save()
		calls = gate_job_calls(enqueue)
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0].kwargs["flight"], flight.name)
		self.assertTrue(calls[0].kwargs["enqueue_after_commit"])
		self.assertNotIn("deduplicate", calls[0].kwargs)

	def test_save_without_gate_change_enqueues_nothing(self):
		flight = make_flight(gate_number="A1")
		with patch("frappe.enqueue") as enqueue:
			flight.save()
		self.assertEqual(gate_job_calls(enqueue), [])

	def test_two_gate_saves_enqueue_two_jobs_and_end_on_latest(self):
		flight = make_flight(gate_number="A1", submit=True)
		ticket = make_ticket(flight)
		flight.reload()
		with patch("frappe.enqueue") as enqueue:
			flight.gate_number = "B2"
			flight.save()
			flight.gate_number = "C3"
			flight.save()
		self.assertEqual(len(gate_job_calls(enqueue)), 2)
		update_ticket_gate_numbers(flight.name)  # whichever job runs last
		self.assertEqual(frappe.db.get_value("Airplane Ticket", ticket.name, "gate_number"), "C3")

	def test_cancelled_ticket_is_skipped(self):
		flight = make_flight(gate_number="A1")
		live = make_ticket(flight)
		cancelled = make_ticket(flight, submit=True)
		cancelled.cancel()
		frappe.db.set_value("Airplane Flight", flight.name, "gate_number", "B7")

		self.assertEqual(update_ticket_gate_numbers(flight.name), 1)  # only the live ticket
		self.assertEqual(frappe.db.get_value("Airplane Ticket", cancelled.name, "gate_number"), "A1")
		self.assertEqual(frappe.db.get_value("Airplane Ticket", live.name, "gate_number"), "B7")

	def test_gate_change_on_draft_flight_enqueues_one_job(self):
		flight = make_flight(gate_number="A1")
		with patch("frappe.enqueue") as enqueue:
			flight.gate_number = "E5"
			flight.save()
		self.assertEqual(len(gate_job_calls(enqueue)), 1)

	def test_job_path_resolves_to_real_function(self):
		self.assertIs(frappe.get_attr(GATE_JOB), update_ticket_gate_numbers)
