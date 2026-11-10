import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from airplane_mode.airport_shops.portal import PUBLIC_FIELDS, get_public_shop, get_public_shops
from airplane_mode.airport_shops.tests.factories import make_contract, make_shop, make_tenant


class TestPortal(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request = None
		frappe.db.rollback()

	def test_list_only_published_shops_with_public_fields(self):
		visible = make_shop()
		hidden = make_shop(published=0)
		names = [s.name for s in get_public_shops()]
		self.assertIn(visible.name, names)
		self.assertNotIn(hidden.name, names)
		shop = next(s for s in get_public_shops() if s.name == visible.name)
		self.assertFalse({"current_tenant", "current_contract", "contract_expiry"} & set(shop))

	def test_detail_hides_unpublished(self):
		self.assertIsNone(get_public_shop(make_shop(published=0).name))
		self.assertIsNone(get_public_shop("does-not-exist"))

	def test_rendered_pages_use_picnic_and_do_not_leak_tenant(self):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		from frappe.website.serve import get_response_content

		tenant = make_tenant()
		shop = make_shop()
		contract = make_contract(shop, tenant, start=add_days(today(), -1), end=add_days(today(), 30))
		frappe.set_user("Guest")
		for path in ("shops", f"shops/{shop.name}"):
			# dynamic route rules (/shops/<shop>) are only evaluated when a request object exists
			frappe.local.request = Request(EnvironBuilder(path=f"/{path}").get_environ())
			content = get_response_content(path)
			self.assertIn(shop.shop_name, content)
			self.assertIn("picnic.min.css", content)  # our own base template, not web.html
			self.assertNotIn(tenant.tenant_name, content)
			self.assertNotIn(contract.name, content)

	def test_public_fields_never_include_tenant_data(self):
		self.assertFalse({"current_tenant", "current_contract", "contract_expiry"} & set(PUBLIC_FIELDS))

	def test_lead_for_unpublished_shop_is_rejected(self):
		shop = make_shop(published=0)
		lead = frappe.get_doc(
			{"doctype": "Shop Lead", "lead_name": "A", "email": "a@example.com", "shop": shop.name}
		)
		self.assertRaises(frappe.ValidationError, lead.insert)

	def test_lead_for_published_shop_is_accepted(self):
		shop = make_shop()
		lead = frappe.get_doc(
			{"doctype": "Shop Lead", "lead_name": "A", "email": "a@example.com", "shop": shop.name}
		).insert()
		self.assertEqual(lead.shop, shop.name)

	def test_description_is_sanitized_on_render(self):
		shop = make_shop()
		frappe.db.set_value("Airport Shop", shop.name, "description", "<img src=x onerror=alert(1)>")
		self.assertNotIn("onerror", get_public_shop(shop.name).description)
