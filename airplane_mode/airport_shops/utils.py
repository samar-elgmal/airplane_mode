import frappe


def update_airport_shop_counts(airport):
	"""Recompute the stored shop counts on an Airport from the Airport Shop table."""
	if not airport or not frappe.db.exists("Airport", airport):
		return
	total = frappe.db.count("Airport Shop", {"airport": airport})
	occupied = frappe.db.count("Airport Shop", {"airport": airport, "status": "Occupied"})
	frappe.db.set_value(
		"Airport",
		airport,
		{"total_shops": total, "occupied_shops": occupied, "available_shops": total - occupied},
		update_modified=False,
	)
