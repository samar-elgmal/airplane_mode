import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.tests.factories import make_airport, make_shop, make_tenant


def counts(airport):
	return frappe.db.get_value(
		"Airport", airport, ["total_shops", "available_shops", "occupied_shops"], as_dict=True
	)


class TestAirportShop(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_name_uses_airport_code(self):
		airport = make_airport("CAI")
		shop = make_shop(airport, number="A12")
		self.assertEqual(shop.name, "CAI-A12")

	def test_duplicate_number_in_same_airport_rejected(self):
		airport = make_airport()
		make_shop(airport, number="B1")
		with self.assertRaises(frappe.ValidationError):
			make_shop(airport, number="B1")

	def test_default_rent_from_settings(self):
		frappe.db.set_single_value("Airport Shop Settings", "default_rent_amount", 750)
		shop = make_shop(rent=0)
		self.assertEqual(shop.rent_amount, 750)

	def test_insert_forces_available_and_clears_tenant(self):
		tenant = make_tenant()
		shop = make_shop(status="Occupied", current_tenant=tenant.name, contract_expiry="2030-01-01")
		self.assertEqual(shop.status, "Available")
		self.assertIsNone(shop.current_tenant)
		self.assertIsNone(shop.contract_expiry)

	def test_protected_fields_cannot_be_changed_by_save(self):
		shop = make_shop()
		shop.status = "Occupied"
		with self.assertRaises(frappe.ValidationError):
			shop.save()

	def test_airport_counts_follow_insert_and_delete(self):
		airport = make_airport()
		shop = make_shop(airport)
		make_shop(airport)
		self.assertEqual(counts(airport.name), {"total_shops": 2, "available_shops": 2, "occupied_shops": 0})
		frappe.delete_doc("Airport Shop", shop.name)
		self.assertEqual(counts(airport.name).total_shops, 1)

	def test_airport_change_updates_both_airports(self):
		old, new = make_airport(), make_airport()
		shop = make_shop(old)
		shop.airport = new.name
		shop.save()
		self.assertEqual(counts(old.name).total_shops, 0)
		self.assertEqual(counts(new.name).total_shops, 1)
