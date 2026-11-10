# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ShopLead(Document):
	def before_insert(self):
		self.status = "New"  # web visitors can't pick their own status
