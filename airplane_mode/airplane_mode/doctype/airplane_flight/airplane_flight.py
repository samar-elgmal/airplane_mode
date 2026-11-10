# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.website.website_generator import WebsiteGenerator


class AirplaneFlight(WebsiteGenerator):
	def validate(self):
		super().validate()
		self.validate_crew()

	def on_submit(self):
		self.status = "Completed"
		self.db_update()

	def validate_crew(self):
		seen = set()
		for row in self.crew:
			if row.crew_member in seen:
				frappe.throw(_("Row {0}: {1} is already on this flight's crew.").format(row.idx, row.crew_member))
			seen.add(row.crew_member)
			# fetch_from is only a UI convenience; the master is the source of truth.
			row.crew_role = frappe.db.get_value("Crew Member", row.crew_member, "crew_role")
