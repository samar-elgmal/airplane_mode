frappe.ready(function () {
	// Frappe builds the form before this runs, so we can set the value directly.
	if (frappe.web_form.is_new) {
		frappe.web_form.set_value("flight_price", 10000);
	}
});
