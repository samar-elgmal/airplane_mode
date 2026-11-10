frappe.ui.form.on("Airplane Ticket", {
    refresh(frm) {
        if (!frm.is_new() && frm.doc.docstatus === 0) {
            frm.add_custom_button(
                "Assign Seat",
                () => {
                    let d = new frappe.ui.Dialog({
                        title: "Assign Seat",
                        fields: [
                            {
                                label: "Seat",
                                fieldname: "seat",
                                fieldtype: "Data",
                                reqd: 1
                            }
                        ],
                        primary_action_label: "Assign",
                        primary_action(values) {
                            frm.set_value("seat", values.seat);
                            d.hide();
                        }
                    });

                    d.show();
                },
                __("Actions")
            );
            frm.page.set_inner_btn_group_as_primary("Actions");
        }
    }
});