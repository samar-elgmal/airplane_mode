from unittest.mock import patch

import frappe
from frappe.query_builder.functions import Coalesce
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from airplane_mode.airport_shops import tasks
from airplane_mode.airport_shops.tests.factories import (
	ensure_outgoing_email_account,
	make_contract,
	make_payment,
	make_shop,
	make_tenant,
)

DUE = "2027-03-01"  # first period of the contract below


def send_rent_reminders(on_date):
	# Never commit from tests: everything must roll back in tearDown.
	return tasks.send_rent_reminders(on_date=on_date, commit=False)


def row(contract, period_start=DUE):
	return frappe.db.get_value(
		"Rent Schedule",
		{"parent": contract.name, "period_start": period_start},
		["name", "reminder_sent_on", "reminder_email", "overdue_reminder_sent_on", "overdue_reminder_email"],
		as_dict=True,
	)


class TestRentReminders(FrappeTestCase):
	def setUp(self):
		self.started = now_datetime()  # same clock (site time zone) as Error Log.creation
		self.contracts = []
		ensure_outgoing_email_account()
		# Isolate from rows already on the site: mark them as reminded inside this test's
		# transaction (rolled back in tearDown), so counts only see this test's contracts
		# and no real tenant gets an Email Queue row, even an uncommitted one.
		# frappe.db.sql(
		# 	"""update `tabRent Schedule`
		# 	set reminder_sent_on = coalesce(reminder_sent_on, '2000-01-01'),
		# 		overdue_reminder_sent_on = coalesce(overdue_reminder_sent_on, '2000-01-01')"""
		# )
		schedule = frappe.qb.DocType("Rent Schedule")
		(
			frappe.qb.update(schedule)
			.set(schedule.reminder_sent_on, Coalesce(schedule.reminder_sent_on, "2000-01-01"))
			.set(schedule.overdue_reminder_sent_on, Coalesce(schedule.overdue_reminder_sent_on, "2000-01-01"))
		).run()
		settings = frappe.get_single("Airport Shop Settings")
		settings.update({"enable_rent_reminders": 1, "reminder_days_before": 3, "overdue_after_days": 3})
		settings.save()
		self.contract = self.make_contract(make_shop())

	def make_contract(self, shop, tenant=None):
		contract = make_contract(shop, tenant, start=DUE, end="2027-05-31")
		self.contracts.append(contract.name)
		return contract

	def tearDown(self):
		row_names = frappe.get_all(
			"Rent Schedule", filters={"parent": ["in", self.contracts]}, pluck="name"
		)
		frappe.db.rollback()
		# Error Log is MyISAM (non-transactional): rollback keeps it, so delete the logs this
		# test wrote for its own rows, and nothing else.
		methods = [
			f"Rent reminder ({kind}) failed for {name}" for name in row_names for kind in tasks.REMINDER_KINDS
		]
		if methods:
			frappe.db.delete("Error Log", {"method": ["in", methods], "creation": [">=", self.started]})

	def test_disabled_sends_nothing(self):
		frappe.db.set_single_value("Airport Shop Settings", "enable_rent_reminders", 0)
		self.assertEqual(send_rent_reminders(on_date="2027-02-27"), {"upcoming": 0, "overdue": 0})

	def test_upcoming_only_inside_window(self):
		self.assertEqual(send_rent_reminders(on_date="2027-02-25")["upcoming"], 0)  # 4 days before
		self.assertEqual(send_rent_reminders(on_date="2027-02-26")["upcoming"], 1)  # 3 days before
		r = row(self.contract)
		self.assertEqual(str(r.reminder_sent_on), "2027-02-26")
		self.assertTrue(frappe.db.exists("Email Queue", r.reminder_email))

	def test_upcoming_not_sent_twice(self):
		send_rent_reminders(on_date="2027-02-27")
		self.assertEqual(send_rent_reminders(on_date="2027-02-28")["upcoming"], 0)

	def test_no_upcoming_after_due_date(self):
		self.assertEqual(send_rent_reminders(on_date="2027-03-02")["upcoming"], 0)

	def test_overdue_sent_once_after_grace_days(self):
		self.assertEqual(send_rent_reminders(on_date="2027-03-03")["overdue"], 0)  # due + 2
		self.assertEqual(send_rent_reminders(on_date="2027-03-04")["overdue"], 1)  # due + 3
		self.assertEqual(send_rent_reminders(on_date="2027-03-05")["overdue"], 0)
		self.assertTrue(frappe.db.exists("Email Queue", row(self.contract).overdue_reminder_email))

	def test_paid_period_skipped(self):
		make_payment(self.contract, DUE, 1000)
		self.assertEqual(send_rent_reminders(on_date="2027-02-27")["upcoming"], 0)

	def test_cancelled_contract_gets_no_reminder(self):
		self.contract.cancel()
		self.assertEqual(send_rent_reminders(on_date="2027-02-27"), {"upcoming": 0, "overdue": 0})
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": self.contract.name}))

	def test_contract_cancelled_after_candidate_selection_is_skipped(self):
		name = row(self.contract).name
		self.contract.cancel()  # between _candidates() and _send_one()
		self.assertFalse(tasks._send_one(name, self.contract.name, "upcoming", "2027-02-27", commit=False))
		self.assertIsNone(row(self.contract).reminder_sent_on)
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": self.contract.name}))

	def test_commit_false_never_commits(self):
		self.make_contract(make_shop(), make_tenant(email="broken@example.com"))
		real_sendmail = frappe.sendmail

		def flaky(*args, **kwargs):  # one row succeeds, one goes through the failure path
			if "broken@example.com" in kwargs.get("recipients", []):
				return []
			return real_sendmail(*args, **kwargs)

		with patch.object(frappe.local.db, "commit", side_effect=AssertionError("commit called")) as commit:
			with patch("frappe.sendmail", side_effect=flaky):
				result = send_rent_reminders(on_date="2027-02-27")
		commit.assert_not_called()
		self.assertEqual(result["upcoming"], 1)

	def test_failed_email_leaves_row_unflagged_and_others_continue(self):
		bad_tenant = make_tenant(email="broken@example.com")
		bad = self.make_contract(make_shop(), bad_tenant)
		real_sendmail = frappe.sendmail
		errors_before = frappe.db.count("Error Log")

		def flaky(*args, **kwargs):
			if "broken@example.com" in kwargs.get("recipients", []):
				raise Exception("SMTP queue unavailable")
			return real_sendmail(*args, **kwargs)

		with patch("frappe.sendmail", side_effect=flaky):
			result = send_rent_reminders(on_date="2027-02-27")

		self.assertEqual(result["upcoming"], 1)
		self.assertIsNone(row(bad).reminder_sent_on)
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": bad.name}))
		self.assertTrue(row(self.contract).reminder_sent_on)
		self.assertGreater(frappe.db.count("Error Log"), errors_before)

	def test_failure_after_queueing_rolls_back_queue_row(self):
		real_sendmail = frappe.sendmail

		def queue_then_fail(*args, **kwargs):
			real_sendmail(*args, **kwargs)  # inserts the Email Queue row
			raise Exception("fails after the row was queued")

		with patch("frappe.sendmail", side_effect=queue_then_fail):
			self.assertEqual(send_rent_reminders(on_date="2027-02-27")["upcoming"], 0)
		self.assertIsNone(row(self.contract).reminder_sent_on)
		self.assertFalse(frappe.db.exists("Email Queue", {"reference_name": self.contract.name}))

	def test_sendmail_returning_nothing_is_not_flagged(self):
		with patch("frappe.sendmail", return_value=[]):
			self.assertEqual(send_rent_reminders(on_date="2027-02-27")["upcoming"], 0)
		self.assertIsNone(row(self.contract).reminder_sent_on)
