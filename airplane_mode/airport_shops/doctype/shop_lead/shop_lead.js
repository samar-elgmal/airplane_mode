frappe.ui.form.on("Shop Lead", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.tenant) {
			frm.add_custom_button(__("New Contract"), () => {
				frappe.new_doc("Shop Contract", { shop: frm.doc.shop, tenant: frm.doc.tenant });
			});
			return;
		}
		frm.add_custom_button(__("Create Tenant"), () => {
			frappe
				.call({
					method: "airplane_mode.airport_shops.doctype.shop_lead.shop_lead.create_tenant",
					args: { lead: frm.doc.name },
					freeze: true,
				})
				.then((r) => {
					frappe.show_alert({ message: __("Tenant {0} linked", [r.message]), indicator: "green" });
					frm.reload_doc();
				});
		});
	},
});
