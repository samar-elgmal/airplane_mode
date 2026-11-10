import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.report.airport_shop_occupancy.airport_shop_occupancy import execute
from airplane_mode.airport_shops.tests.factories import make_airport, make_contract, make_shop


class TestOccupancyReport(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_counts_are_computed_live(self):
		airport = make_airport()
		occupied = make_shop(airport)
		make_shop(airport)
		make_contract(occupied, start=add_days(today(), -1), end=add_days(today(), 30))
		frappe.db.set_value("Airport", airport.name, "total_shops", 99)  # stored value is ignored

		columns, data, _message, chart = execute({"airport": airport.name})

		self.assertEqual(len(data), 1)
		self.assertEqual((data[0].total, data[0].available, data[0].occupied), (2, 1, 1))
		self.assertEqual(data[0].occupancy, 50.0)
		self.assertEqual(chart["type"], "bar")
