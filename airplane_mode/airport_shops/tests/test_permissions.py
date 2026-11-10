import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.tests.factories import make_contract, make_shop, unique


def make_user(role):
	email = f"{unique('api')}@example.com"
	frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "API", "send_welcome_email": 0, "roles": [{"role": role}]}
	).insert(ignore_permissions=True)
	return email


class TestShopFieldPermissions(FrappeTestCase):
	def setUp(self):
		self.shop = make_shop()
		make_contract(self.shop, start=add_days(today(), -1), end=add_days(today(), 30))

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _row_as(self, role):
		frappe.set_user(make_user(role))
		rows = frappe.get_list("Airport Shop", fields=["*"], filters={"name": self.shop.name})
		frappe.set_user("Administrator")
		return rows[0]

	def test_travel_agent_does_not_see_tenant_fields(self):
		row = self._row_as("Travel Agent")
		self.assertIn("status", row)
		self.assertNotIn("current_tenant", row)
		self.assertNotIn("current_contract", row)

	def test_airport_authority_sees_tenant_fields(self):
		row = self._row_as("Airport Authority Personnel")
		self.assertTrue(row.get("current_tenant"))
