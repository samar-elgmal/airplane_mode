# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, today

from airplane_mode.airport_shops.utils import sync_shop_status, update_airport_shop_counts

# Only sync_shop_status (via frappe.db.set_value, which skips validate) may write these.
PROTECTED_FIELDS = ("status", "current_tenant", "current_contract", "contract_expiry")


class AirportShop(Document):
	def autoname(self):
		code = frappe.db.get_value("Airport", self.airport, "code") or self.airport
		self.name = f"{code}-{self.shop_number}".strip()

	def before_insert(self):
		self.status = "Available"
		for fieldname in PROTECTED_FIELDS[1:]:
			self.set(fieldname, None)
		if not flt(self.rent_amount):
			self.rent_amount = flt(frappe.db.get_single_value("Airport Shop Settings", "default_rent_amount"))

	def validate(self):
		self.validate_unique_shop_number()
		if not self.is_new():
			self.validate_protected_fields()
			self.validate_airport_change()

	def on_update(self):
		# Also refreshes this airport's counts. Reload when it wrote, so the in-memory doc
		# (and the form) doesn't hold a stale status/modified.
		if sync_shop_status(self.name):
			self.reload()
		before = self.get_doc_before_save()
		if before and before.airport != self.airport:
			update_airport_shop_counts(before.airport)

	def after_delete(self):
		update_airport_shop_counts(self.airport)

	def validate_unique_shop_number(self):
		filters = {"airport": self.airport, "shop_number": self.shop_number}
		if not self.is_new():
			# autoname already set self.name on a new doc, so only exclude self when it is saved.
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Airport Shop", filters):
			frappe.throw(_("Shop number {0} already exists at airport {1}.").format(self.shop_number, self.airport))
		if self.is_new() and frappe.db.exists("Airport Shop", self.name):
			frappe.throw(
				_("A shop named {0} already exists (another airport may use the same code).").format(self.name)
			)

	def validate_protected_fields(self):
		before = self.get_doc_before_save()
		if not before:
			return
		for fieldname in PROTECTED_FIELDS:
			# cstr() so a date from the DB and a date string from the API compare equal.
			if cstr(before.get(fieldname)) != cstr(self.get(fieldname)):
				frappe.throw(
					_("{0} is set automatically from shop contracts and cannot be changed by hand.").format(
						self.meta.get_label(fieldname)
					)
				)

	def validate_airport_change(self):
		before = self.get_doc_before_save()
		if not before or before.airport == self.airport:
			return
		if frappe.db.exists("Shop Contract", {"shop": self.name, "docstatus": 1, "end_date": [">=", today()]}):
			frappe.throw(_("This shop has an active or upcoming contract, so its airport cannot be changed."))
