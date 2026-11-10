from frappe import _


def get_data():
	# The lead points at its Tenant and Shop Contract through its own fields (internal links).
	return {
		"fieldname": "shop_lead",
		"internal_links": {"Tenant": "tenant", "Shop Contract": "shop_contract"},
		"transactions": [{"label": _("Leasing"), "items": ["Tenant", "Shop Contract"]}],
	}
