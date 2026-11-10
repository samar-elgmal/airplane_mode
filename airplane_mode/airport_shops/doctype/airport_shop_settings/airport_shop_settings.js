frappe.ui.form.on("Airport Shop Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Reminders Now"), () => {
			frappe
				.call("airplane_mode.airport_shops.doctype.airport_shop_settings.airport_shop_settings.enqueue_rent_reminders")
				.then((r) => frappe.show_alert({ message: r.message, indicator: "green" }));
		});
	},
});
