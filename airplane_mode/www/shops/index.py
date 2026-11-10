import frappe

from airplane_mode.airport_shops.portal import get_public_airports, get_public_shops

no_cache = 1


def get_context(context):
	airport = frappe.form_dict.get("airport") or None
	context.selected_airport = airport
	context.airports = get_public_airports()
	context.shops = get_public_shops(airport)
	return context
