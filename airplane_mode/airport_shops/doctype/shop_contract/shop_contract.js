frappe.ui.form.on("Shop Contract", {
	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Record Payment"), () => {
				frappe.new_doc("Rent Payment", { shop_contract: frm.doc.name });
			});
		}
	},
});
