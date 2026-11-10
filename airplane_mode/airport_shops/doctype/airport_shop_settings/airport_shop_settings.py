# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class AirportShopSettings(Document):
	def validate(self):
		if cint(self.reminder_days_before) < 0:
			frappe.throw(_("Days before due date cannot be negative."))
		if cint(self.overdue_after_days) < 1:
			frappe.throw(_("Overdue reminder must be at least 1 day after the due date."))


@frappe.whitelist()
def enqueue_rent_reminders():
	"""Button handler: queue the reminder job instead of doing the work in the web request."""
	frappe.only_for(("System Manager", "Airport Authority Personnel"))
	frappe.enqueue(
		"airplane_mode.airport_shops.tasks.send_rent_reminders", queue="short", enqueue_after_commit=True
	)
	return _("Reminders queued")
