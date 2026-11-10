import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airplane_mode.tests.factories import make_crew_member, make_flight


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
