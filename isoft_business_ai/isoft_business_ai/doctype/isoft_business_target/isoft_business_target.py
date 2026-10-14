import frappe
from frappe.model.document import Document


class IsoftBusinessTarget(Document):
	def validate(self):
		if self.period_end and self.period_start and self.period_end < self.period_start:
			frappe.throw("Period end cannot be before period start.")
		if self.target_amount is not None and self.target_amount <= 0:
			frappe.throw("A target amount must be positive.")
