import frappe

from airplane_mode.airplane_mode.tests.factories import make_airport, unique

__all__ = [
	"make_airport",
	"make_shop",
	"make_tenant",
	"make_contract",
	"make_payment",
	"ensure_outgoing_email_account",
]


def make_shop(airport=None, number=None, rent=1000, **extra):
	airport = airport or make_airport()
	return frappe.get_doc(
		{
			"doctype": "Airport Shop",
			"airport": airport.name if hasattr(airport, "name") else airport,
			"shop_number": number or frappe.generate_hash(length=4).upper(),
			"shop_name": unique("Shop"),
			"shop_type": "Normal",
			"area": 120,
			"rent_amount": rent,
			**extra,
		}
	).insert()


def make_tenant(email=None):
	return frappe.get_doc(
		{"doctype": "Tenant", "tenant_name": unique("Tenant"), "email": email or f"{unique('t')}@example.com"}
	).insert()


def make_contract(shop, tenant=None, start="2026-11-15", end="2027-02-14", rent=1000, submit=True):
	tenant = tenant or make_tenant()
	doc = frappe.get_doc(
		{
			"doctype": "Shop Contract",
			"shop": shop.name,
			"tenant": tenant.name,
			"start_date": start,
			"end_date": end,
			"rent_amount": rent,
		}
	).insert()
	if submit:
		doc.submit()
	return doc


def make_payment(contract, period_start, amount, submit=True):
	doc = frappe.get_doc(
		{
			"doctype": "Rent Payment",
			"shop_contract": contract.name,
			"period_start": period_start,
			"amount": amount,
			"mode_of_payment": "Cash",
		}
	).insert()
	if submit:
		doc.submit()
	return doc


def ensure_outgoing_email_account():
	"""frappe.sendmail needs a default outgoing account. Tests skip the SMTP check."""
	if frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
		return
	frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": "Rent Test Outgoing",
			"email_id": "rent-test@example.com",
			"enable_outgoing": 1,
			"default_outgoing": 1,
			"smtp_server": "localhost",
			"smtp_port": 25,
			"no_smtp_authentication": 1,
		}
	).insert(ignore_permissions=True)
