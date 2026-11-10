from urllib.parse import quote

import frappe

from airplane_mode.airport_shops.portal import get_public_shop

no_cache = 1


def get_context(context):
	shop = get_public_shop(frappe.form_dict.get("shop"))
	if not shop:
		raise frappe.DoesNotExistError
	context.shop = shop
	context.lead_url = f"/shop-lead/new?shop={quote(shop.name)}"
	return context
