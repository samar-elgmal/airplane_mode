from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.doctype.airport_shop_settings.airport_shop_settings import (
	enqueue_rent_reminders,
)

REMINDER_JOB = "airplane_mode.airport_shops.tasks.send_rent_reminders"


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

	def test_send_now_enqueues_reminder_job_after_commit(self):
		from airplane_mode.airport_shops.tasks import send_rent_reminders

		with patch("frappe.enqueue") as enqueue:
			enqueue_rent_reminders()

		enqueue.assert_called_once()
		args, kwargs = enqueue.call_args
		self.assertEqual(args[0] if args else kwargs.get("method"), REMINDER_JOB)
		self.assertIs(kwargs.get("enqueue_after_commit"), True)
		self.assertIs(frappe.get_attr(REMINDER_JOB), send_rent_reminders)
