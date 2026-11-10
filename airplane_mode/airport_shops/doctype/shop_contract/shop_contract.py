# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from airplane_mode.airport_shops.doctype.shop_lead.shop_lead import convert_leads_for_contract
from airplane_mode.airport_shops.utils import build_rent_schedule, sync_shop_status


class ShopContract(Document):
	def validate(self):
		if getdate(self.end_date) < getdate(self.start_date):
			frappe.throw(_("End Date cannot be before Start Date."))
		if flt(self.rent_amount) <= 0:
			frappe.throw(_("Monthly Rent must be greater than zero."))
		self.validate_no_overlap()
		if self.docstatus == 0:
			# Drafts never carry a schedule. This also drops rows copied by Amend
			# (paid amounts, reminder flags, email links).
			self.set("rent_schedule", [])
			self.total_amount = self.total_paid = self.total_outstanding = 0

	def before_submit(self):
		# Lock the shop so two contracts for it can't be submitted at the same time,
		# then re-check the overlap while holding the lock.
		frappe.db.sql("select name from `tabAirport Shop` where name = %s for update", self.shop)
		self.validate_no_overlap(for_update=True)
		self.make_rent_schedule()

	def on_submit(self):
		sync_shop_status(self.shop)
		convert_leads_for_contract(self)

	def before_cancel(self):
		# Lock order matters: a Rent Payment submit locks its own row first, then this contract.
		# So never lock Rent Payment rows here (contract -> payment would invert that order and
		# can deadlock). Payments update total_paid while holding this same contract lock, so a
		# locking read of it (FOR UPDATE sees the latest committed value, not the REPEATABLE READ
		# snapshot) is current.
		total_paid = frappe.db.sql(
			"select total_paid from `tabShop Contract` where name = %s for update", self.name
		)[0][0]
		if flt(total_paid) > 0:
			frappe.throw(_("Cancel the submitted Rent Payments of this contract first."))

	def on_cancel(self):
		sync_shop_status(self.shop)

	def validate_no_overlap(self, for_update=False):
		if for_update:
			# Locking read: under REPEATABLE READ a plain SELECT would reuse the snapshot taken
			# at the first read in validate() and miss a contract committed while we waited
			# for the shop lock. FOR UPDATE reads the latest committed rows.
			rows = frappe.db.sql(
				"""select name from `tabShop Contract`
				where shop = %s and docstatus = 1 and name != %s and start_date <= %s and end_date >= %s
				limit 1 for update""",
				(self.shop, self.name, self.end_date, self.start_date),
			)
			clash = rows[0][0] if rows else None
		else:
			clash = frappe.db.get_value(
				"Shop Contract",
				{
					"shop": self.shop,
					"docstatus": 1,
					"name": ["!=", self.name],
					"start_date": ["<=", self.end_date],
					"end_date": [">=", self.start_date],
				},
				"name",
			)
		if clash:
			frappe.throw(_("Shop {0} already has contract {1} for these dates.").format(self.shop, clash))

	def make_rent_schedule(self):
		precision = self.precision("amount", "rent_schedule") or 2
		self.set("rent_schedule", [])
		for row in build_rent_schedule(self.start_date, self.end_date, self.rent_amount, precision):
			self.append("rent_schedule", row)
		total_precision = self.precision("total_amount") or 2
		self.total_amount = flt(sum(flt(r.amount) for r in self.rent_schedule), total_precision)
		self.total_paid = 0
		self.total_outstanding = self.total_amount
