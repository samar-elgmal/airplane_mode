# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from airplane_mode.airport_shops.utils import update_contract_totals


class RentPayment(Document):
	def validate(self):
		p = self.precision("amount") or 2
		if flt(self.amount, p) <= 0:
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
		if flt(flt(self.amount) - flt(row.outstanding_amount), p) > 0:
			frappe.throw(_("Amount is more than the outstanding {0} for this period.").format(self.period_outstanding))

	def on_submit(self):
		p = self.precision("amount") or 2
		row = self._lock_period()
		new_paid = flt(flt(row.paid_amount) + flt(self.amount), p)
		if flt(new_paid - flt(row.amount), p) > 0:
			frappe.throw(_("This payment would overpay the period. Another payment was recorded first."))
		outstanding = self._apply(row, new_paid)
		self.db_set("period_outstanding_after_payment", outstanding)  # receipt snapshot

	def on_cancel(self):
		p = self.precision("amount") or 2
		row = self._lock_period()
		self._apply(row, max(flt(flt(row.paid_amount) - flt(self.amount), p), 0))

	def _lock_period(self):
		"""The only lock path for payments: contract row first, then the period row."""
		if not frappe.db.sql(
			"select name from `tabShop Contract` where name = %s and docstatus = 1 for update",
			self.shop_contract,
		):
			frappe.throw(_("Shop Contract {0} is not submitted.").format(self.shop_contract))
		rows = frappe.db.sql(
			"""select name, amount, paid_amount from `tabRent Schedule`
			where parent = %s and parenttype = 'Shop Contract' and period_start = %s
			for update""",
			(self.shop_contract, self.period_start),
			as_dict=True,
		)
		if not rows:
			frappe.throw(_("Contract {0} has no rent period starting on {1}.").format(self.shop_contract, self.period_start))
		return rows[0]

	def _apply(self, row, new_paid):
		p = self.precision("amount") or 2
		outstanding = max(flt(flt(row.amount) - new_paid, p), 0)
		if outstanding <= 0:
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
