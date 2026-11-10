frappe.ready(function () {
	// /shop-lead/new?shop=CAI-A12 pre-fills the shop the visitor came from.
	const shop = frappe.utils.get_query_params().shop;
	if (!shop) return;
	frappe.web_form.after_load = () => frappe.web_form.set_value("shop", shop);
	if (frappe.web_form.fields_dict && frappe.web_form.fields_dict.shop) {
		frappe.web_form.set_value("shop", shop);
	}
});
