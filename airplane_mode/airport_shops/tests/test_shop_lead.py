import frappe
from frappe.tests.utils import FrappeTestCase

from airplane_mode.airport_shops.doctype.shop_lead.shop_lead import create_tenant
from airplane_mode.airport_shops.tests.factories import make_contract, make_shop, make_tenant, unique


def make_lead(shop, email=None, status="New"):
	return frappe.get_doc(
		{
			"doctype": "Shop Lead",
			"lead_name": unique("Lead"),
			"email": email or f"{unique('lead')}@example.com",
			"phone": "+20 100 000 0000",
			"shop": shop.name,
			"status": status,
		}
	).insert()


def lead_state(lead):
	return frappe.db.get_value("Shop Lead", lead.name, ["status", "tenant"], as_dict=True)


class TestCreateTenantFromLead(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_creates_tenant_from_lead_details_and_marks_contacted(self):
		lead = make_lead(make_shop())
		tenant_name = create_tenant(lead.name)

		tenant = frappe.get_doc("Tenant", tenant_name)
		self.assertEqual(
			(tenant.tenant_name, tenant.email, tenant.phone), (lead.lead_name, lead.email, lead.phone)
		)
		self.assertEqual(lead_state(lead), {"status": "Contacted", "tenant": tenant_name})

	def test_reuses_existing_tenant_with_same_email(self):
		existing = make_tenant(email=f"{unique('same')}@example.com")
		lead = make_lead(make_shop(), email=existing.email)
		count_before = frappe.db.count("Tenant")

		self.assertEqual(create_tenant(lead.name), existing.name)
		self.assertEqual(frappe.db.count("Tenant"), count_before)

	def test_second_click_returns_same_tenant(self):
		lead = make_lead(make_shop())
		first = create_tenant(lead.name)
		self.assertEqual(create_tenant(lead.name), first)

	def test_does_not_downgrade_a_lost_lead(self):
		lead = make_lead(make_shop(), status="Lost")
		create_tenant(lead.name)
		self.assertEqual(lead_state(lead).status, "Lost")

	def test_needs_write_permission_on_the_lead(self):
		lead = make_lead(make_shop())
		user = f"{unique('agent')}@example.com"
		frappe.get_doc(
			{"doctype": "User", "email": user, "first_name": "Agent", "send_welcome_email": 0,
			 "roles": [{"role": "Travel Agent"}]}
		).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				create_tenant(lead.name)
		finally:
			frappe.set_user("Administrator")


class TestAutoConvertLeads(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_open_lead_with_tenant_email_is_converted_on_submit(self):
		shop = make_shop()
		tenant = make_tenant()
		matching = make_lead(shop, email=tenant.email, status="Contacted")
		new_matching = make_lead(shop, email=tenant.email)

		make_contract(shop, tenant, start="2027-01-01", end="2027-03-31")

		self.assertEqual(lead_state(matching).status, "Converted")
		self.assertEqual(lead_state(new_matching).status, "Converted")

	def test_lead_linked_to_tenant_is_converted_even_with_other_email(self):
		shop = make_shop()
		lead = make_lead(shop)
		tenant_name = create_tenant(lead.name)
		frappe.db.set_value("Tenant", tenant_name, "email", f"{unique('changed')}@example.com")

		make_contract(shop, frappe.get_doc("Tenant", tenant_name), start="2027-01-01", end="2027-03-31")

		self.assertEqual(lead_state(lead).status, "Converted")

	def test_other_leads_are_left_alone(self):
		shop, other_shop = make_shop(), make_shop()
		tenant = make_tenant()
		other_person = make_lead(shop)
		other_shop_lead = make_lead(other_shop, email=tenant.email)
		lost = make_lead(shop, email=tenant.email, status="Lost")

		make_contract(shop, tenant, start="2027-01-01", end="2027-03-31")

		self.assertEqual(lead_state(other_person).status, "New")
		self.assertEqual(lead_state(other_shop_lead).status, "New")
		self.assertEqual(lead_state(lost).status, "Lost")

	def test_converted_lead_links_to_its_contract(self):
		shop, tenant = make_shop(), make_tenant()
		lead = make_lead(shop, email=tenant.email)
		contract = make_contract(shop, tenant, start="2027-01-01", end="2027-03-31")
		self.assertEqual(frappe.db.get_value("Shop Lead", lead.name, "shop_contract"), contract.name)
		self.assertEqual(frappe.db.get_value("Shop Lead", lead.name, "tenant"), tenant.name)  # matched by email

	def test_cancelled_contract_reopens_its_leads(self):
		shop, tenant = make_shop(), make_tenant()
		lead = make_lead(shop, email=tenant.email)
		contract = make_contract(shop, tenant, start="2027-01-01", end="2027-03-31")
		contract.reload()
		contract.cancel()
		state = frappe.db.get_value("Shop Lead", lead.name, ["status", "shop_contract"], as_dict=True)
		self.assertEqual((state.status, state.shop_contract), ("Contacted", None))

	def test_draft_contract_does_not_convert(self):
		shop = make_shop()
		tenant = make_tenant()
		lead = make_lead(shop, email=tenant.email)
		make_contract(shop, tenant, start="2027-01-01", end="2027-03-31", submit=False)
		self.assertEqual(lead_state(lead).status, "New")


class TestLeadConnections(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _connections(self, doctype, name):
		from frappe.desk.notifications import get_open_count

		found = get_open_count(doctype, name)["count"]
		return {d["doctype"]: d.get("names") or d["count"] for d in found["internal_links_found"]} | {
			d["doctype"]: d["count"] for d in found["external_links_found"] if d["count"]
		}

	def test_lead_shows_its_tenant_and_contract(self):
		shop = make_shop()
		lead = make_lead(shop)
		tenant = create_tenant(lead.name)
		contract = make_contract(shop, frappe.get_doc("Tenant", tenant), start="2027-01-01", end="2027-03-31")

		links = self._connections("Shop Lead", lead.name)
		self.assertEqual(links["Tenant"], [tenant])
		self.assertEqual(links["Shop Contract"], [contract.name])

	def test_tenant_and_contract_show_the_lead(self):
		shop = make_shop()
		lead = make_lead(shop)
		tenant = create_tenant(lead.name)
		contract = make_contract(shop, frappe.get_doc("Tenant", tenant), start="2027-01-01", end="2027-03-31")

		self.assertEqual(self._connections("Tenant", tenant).get("Shop Lead"), 1)
		self.assertEqual(self._connections("Shop Contract", contract.name).get("Shop Lead"), 1)
