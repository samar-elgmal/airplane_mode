# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from airplane_mode.airport_shops.utils import update_contract_totals


def money_precision():
	"""Payments settle Rent Schedule rows, so they round to the schedule's precision."""
	return frappe.get_precision("Rent Schedule", "amount") or 2


def inconsistent():
	frappe.throw(_("Rent Schedule row is inconsistent with its payments."))


class RentPayment(Document):
	def validate(self):
		p = money_precision()
		self.amount = flt(self.amount, p)
		if self.amount <= 0:
			frappe.throw(_("Amount Paid must be greater than zero."))

		contract = frappe.db.get_value(
			"Shop Contract", self.shop_contract, ["docstatus", "shop", "tenant", "tenant_email"], as_dict=True
		)
		if not contract or contract.docstatus != 1:
			frappe.throw(_("Shop Contract {0} is not submitted.").format(self.shop_contract))
		self.shop, self.tenant, self.tenant_email = contract.shop, contract.tenant, contract.tenant_email

		row = frappe.db.get_value(
			"Rent Schedule",
			{"parent": self.shop_contract, "parenttype": "Shop Contract", "period_start": self.period_start},
			["outstanding_amount"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("Contract {0} has no rent period starting on {1}.").format(self.shop_contract, self.period_start))
		self.period_outstanding = flt(row.outstanding_amount, p)
		# Early, friendly check. The authoritative check runs under a lock in on_submit.
		if flt(self.amount - flt(row.outstanding_amount), p) > 0:
			frappe.throw(_("Amount is more than the outstanding {0} for this period.").format(self.period_outstanding))

	def on_submit(self):
		p = money_precision()
		row = self._lock_period()
		# Refresh from the locked row: validate's value came from an unlocked snapshot.
		self.db_set("period_outstanding", flt(flt(row.amount) - flt(row.paid_amount), p))
		new_paid = flt(flt(row.paid_amount) + flt(self.amount), p)
		if flt(new_paid - flt(row.amount), p) > 0:
			frappe.throw(_("This payment would overpay the period. Another payment was recorded first."))
		outstanding = self._apply(row, new_paid)
		self.db_set("period_outstanding_after_payment", outstanding)  # receipt snapshot

	def on_cancel(self):
		p = money_precision()
		row = self._lock_period()
		new_paid = flt(flt(row.paid_amount) - flt(self.amount), p)
		if new_paid < 0:
			inconsistent()
		self._apply(row, new_paid)

	def _lock_period(self):
		"""The only lock path for payments: contract row first, then the period row."""
		# if not frappe.db.sql(
		# 	"select name from `tabShop Contract` where name = %s and docstatus = 1 for update",
		# 	self.shop_contract,
		# ):
		if not frappe.db.get_value(
			"Shop Contract", {"name": self.shop_contract, "docstatus": 1}, "name", for_update=True
		):
			frappe.throw(_("Shop Contract {0} is not submitted.").format(self.shop_contract))
		# rows = frappe.db.sql(
		# 	"""select name, amount, paid_amount from `tabRent Schedule`
		# 	where parent = %s and parenttype = 'Shop Contract' and period_start = %s
		# 	for update""",
		# 	(self.shop_contract, self.period_start),
		# 	as_dict=True,
		# )
		row = frappe.db.get_value(
			"Rent Schedule",
			{"parent": self.shop_contract, "parenttype": "Shop Contract", "period_start": self.period_start},
			["name", "amount", "paid_amount"],
			as_dict=True,
			for_update=True,
		)
		if not row:
			frappe.throw(_("Contract {0} has no rent period starting on {1}.").format(self.shop_contract, self.period_start))
		return row

	def _apply(self, row, new_paid):
		p = money_precision()
		outstanding = flt(flt(row.amount) - new_paid, p)
		if outstanding < 0:
			inconsistent()
		if outstanding == 0:
			status = "Paid"
		elif new_paid > 0:
			status = "Partly Paid"
		else:
			status = "Unpaid"
		frappe.db.set_value(
			"Rent Schedule",
			row.name,
			{"paid_amount": new_paid, "outstanding_amount": outstanding, "status": status},
			update_modified=False,
		)
		update_contract_totals(self.shop_contract)
		return outstanding


@frappe.whitelist()
def get_open_periods(shop_contract):
	frappe.has_permission("Shop Contract", "read", shop_contract, throw=True)
	return frappe.get_all(
		"Rent Schedule",
		filters={"parent": shop_contract, "parenttype": "Shop Contract", "status": ["!=", "Paid"]},
		fields=["period_start", "period_end", "outstanding_amount"],
		order_by="period_start asc",
	)
