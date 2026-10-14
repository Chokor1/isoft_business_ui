frappe.ui.form.on('Isoft Business AI Settings', {
	refresh(frm) {
		frm.add_custom_button(__('Test connection'), () => {
			frappe.dom.freeze(__('Contacting the API…'));
			frappe.call({
				method: 'isoft_business_ai.api.test_connection',
				callback: r => {
					frappe.dom.unfreeze();
					frm.reload_doc();
					const ok = r.message && r.message.ok;
					frappe.msgprint({
						title: ok ? __('Connection OK') : __('Connection failed'),
						indicator: ok ? 'green' : 'red',
						message: ok
							? __('Model {0} responded correctly.', [r.message.model])
							: frappe.utils.escape_html(
									(r.message && r.message.error) || __('Unknown error')
							  ),
					});
				},
				error: () => frappe.dom.unfreeze(),
			});
		});

		if (!frm.doc.enabled) {
			frm.dashboard.set_headline_alert(
				__('The assistant is disabled. No questions will be processed.'),
				'orange'
			);
		}
	},
});
