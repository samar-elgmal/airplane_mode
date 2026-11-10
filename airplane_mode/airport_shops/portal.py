"""Public (Guest) queries for the shop website.

frappe.get_all ignores permissions, so permlevel doesn't protect anything here. Only the
fields listed below ever reach a template.
"""
import frappe
from frappe.utils import fmt_money

PUBLIC_FIELDS = [
	"name",
	"shop_name",
	"shop_number",
	"airport",
	"shop_type",
	"area",
	"rent_amount",
	"status",
	"image",
	"description",
]


def _decorate(shop):
	shop.rent_display = fmt_money(shop.rent_amount, currency=frappe.db.get_default("currency"))
	return shop


def get_public_shops(airport=None):
	filters = {"published": 1}
	if airport:
		filters["airport"] = airport
	shops = frappe.get_all("Airport Shop", filters=filters, fields=PUBLIC_FIELDS, order_by="airport asc, shop_number asc")
	return [_decorate(shop) for shop in shops]


def get_public_shop(name):
	if not name:
		return None
	rows = frappe.get_all("Airport Shop", filters={"name": name, "published": 1}, fields=PUBLIC_FIELDS, limit=1)
	return _decorate(rows[0]) if rows else None


def get_public_airports():
	return frappe.get_all("Airport Shop", filters={"published": 1}, pluck="airport", distinct=True, order_by="airport asc")
