import frappe
from frappe.model.document import Document


class IsoftBusinessAISettings(Document):
	def on_update(self):
		"""Drop the cached bootinfo so the widget appears or disappears at once.

		bootinfo is a redis hash keyed by user, so the whole hash goes; without
		this, toggling `enabled` would only take effect when the cache expired.
		"""
		frappe.cache().delete_key("bootinfo")
		frappe.clear_cache()
