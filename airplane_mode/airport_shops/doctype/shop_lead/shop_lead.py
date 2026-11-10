# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ShopLead(Document):
	def before_insert(self):
		if frappe.flags.in_web_form:
			self.status = "New"  # web visitors can't pick their own status

	def validate(self):
		if self.shop and frappe.db.get_value("Airport Shop", self.shop, "published") != 1:
			frappe.throw(_("This shop is not available."), frappe.ValidationError)
