# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.website.website_generator import WebsiteGenerator


class AirplaneFlight(WebsiteGenerator):
	def validate(self):
		super().validate()
		self.validate_crew()

	def on_update(self):
		super().on_update()
		self.enqueue_gate_update()

	def on_submit(self):
		self.status = "Completed"
		self.db_update()

	def on_update_after_submit(self):
		self.enqueue_gate_update()

	def validate_crew(self):
		seen = set()
		for row in self.crew:
			if row.crew_member in seen:
				frappe.throw(_("Row {0}: {1} is already on this flight's crew.").format(row.idx, row.crew_member))
			seen.add(row.crew_member)
			# fetch_from is only a UI convenience; the master is the source of truth.
			row.crew_role = frappe.db.get_value("Crew Member", row.crew_member, "crew_role")

	def enqueue_gate_update(self):
		# A brand-new flight has no tickets yet, so there is nothing to update.
		if not self.get_doc_before_save() or not self.has_value_changed("gate_number"):
			return
		# No job_id/deduplicate: in v15 dedupe also skips while the old job is STARTED,
		# which could drop the latest gate. The job is idempotent, so extra runs are safe.
		frappe.enqueue(
			"airplane_mode.airplane_mode.tasks.update_ticket_gate_numbers",
			flight=self.name,
			queue="short",
			enqueue_after_commit=True,
		)
