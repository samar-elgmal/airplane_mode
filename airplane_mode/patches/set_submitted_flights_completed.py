import frappe


def execute():
	"""Mark flights that were submitted before the on_submit hook existed as Completed."""
	flights = frappe.get_all(
		"Airplane Flight",
		filters={"docstatus": 1, "status": ["!=", "Completed"]},
		pluck="name",
	)

	for name in flights:
		frappe.db.set_value("Airplane Flight", name, "status", "Completed", update_modified=False)
