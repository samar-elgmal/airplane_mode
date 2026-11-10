import frappe
from frappe.tests.utils import FrappeTestCase


class TestAirportShopSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_negative_days_before_rejected(self):
		settings = frappe.get_single("Airport Shop Settings")
		settings.reminder_days_before = -1
		with self.assertRaises(frappe.ValidationError):
			settings.save()

	def test_overdue_days_must_be_positive(self):
		settings = frappe.get_single("Airport Shop Settings")
		settings.reminder_days_before = 3
		settings.overdue_after_days = 0
		with self.assertRaises(frappe.ValidationError):
			settings.save()
