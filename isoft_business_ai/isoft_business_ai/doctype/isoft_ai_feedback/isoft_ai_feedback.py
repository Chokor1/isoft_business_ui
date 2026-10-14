# -*- coding: utf-8 -*-
"""A user's report that an answer was wrong.

Deliberately inert. Nothing here feeds back into a tool, a definition or a
prompt on its own: one person's opinion must not silently change what everyone
else is told. A report is evidence for a human to investigate, and the tools
that ran are stored with it so a confirmed fault can become a gold-set case.
"""

import frappe
from frappe.model.document import Document


class IsoftAIFeedback(Document):
    def validate(self):
        if not self.reported_on:
            self.reported_on = frappe.utils.now()
