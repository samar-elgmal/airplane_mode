frappe.ui.form.on("Rent Payment", {
	setup(frm) {
		frm.set_query("shop_contract", () => ({ filters: { docstatus: 1 } }));
	},
	onload(frm) {
		if (frm.is_new() && frm.doc.shop_contract && !frm.doc.period_start) {
			frm.trigger("shop_contract");
		}
	},
	shop_contract(frm) {
		if (!frm.doc.shop_contract) return;
		frappe
			.call({
				method: "airplane_mode.airport_shops.doctype.rent_payment.rent_payment.get_open_periods",
				args: { shop_contract: frm.doc.shop_contract },
			})
			.then((r) => {
				const periods = r.message || [];
				if (!periods.length) {
					frappe.msgprint(__("All rent periods of this contract are paid."));
					return;
				}
				frm.set_value("period_start", periods[0].period_start);
				frm.set_value("amount", periods[0].outstanding_amount);
			});
	},
});
