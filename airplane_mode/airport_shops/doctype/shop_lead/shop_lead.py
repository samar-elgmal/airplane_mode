# Copyright (c) 2026, samar and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

OPEN_STATUSES = ("New", "Contacted")


class ShopLead(Document):
	def before_insert(self):
		if frappe.flags.in_web_form:
			self.status = "New"  # web visitors can't pick their own status

	def validate(self):
		if self.shop and frappe.db.get_value("Airport Shop", self.shop, "published") != 1:
			frappe.throw(_("This shop is not available."), frappe.ValidationError)


@frappe.whitelist()
def create_tenant(lead):
	"""Make (or reuse) a Tenant from the lead's details and link it. Returns the Tenant name.

	A New lead moves to Contacted; other statuses are left as they are.
	"""
	doc = frappe.get_doc("Shop Lead", lead)
	doc.check_permission("write")
	if doc.tenant:
		return doc.tenant

	tenant = frappe.db.get_value("Tenant", {"email": doc.email}, "name")
	if not tenant:
		tenant = (
			frappe.get_doc(
				{"doctype": "Tenant", "tenant_name": doc.lead_name, "email": doc.email, "phone": doc.phone}
			)
			.insert()
			.name
		)

	doc.tenant = tenant
	if doc.status == "New":
		doc.status = "Contacted"
	doc.save()
	return tenant


def convert_leads_for_contract(contract):
	"""A submitted contract converts the open leads for its shop that belong to its tenant.

	A lead belongs to the tenant when it is linked to it (via Create Tenant) or uses its email.
	"""
	leads = frappe.get_all(
		"Shop Lead",
		filters={"shop": contract.shop, "status": ["in", OPEN_STATUSES]},
		or_filters={"tenant": contract.tenant, "email": contract.tenant_email or ""},
		pluck="name",
	)
	for lead in leads:
		# A lead matched by email gets linked to the tenant too, so its Connections show both.
		frappe.db.set_value(
			"Shop Lead", lead, {"status": "Converted", "shop_contract": contract.name, "tenant": contract.tenant}
		)
	return leads


def reopen_leads_for_contract(contract):
	"""A cancelled contract puts its converted leads back to Contacted, so an amendment can convert them again."""
	leads = frappe.get_all(
		"Shop Lead", filters={"shop_contract": contract.name, "status": "Converted"}, pluck="name"
	)
	for lead in leads:
		frappe.db.set_value("Shop Lead", lead, {"status": "Contacted", "shop_contract": None})
	return leads
