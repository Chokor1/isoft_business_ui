"""Write guards — currently disabled.

The assistant is READ-ONLY by decision: quotations and other documents are
created in a separate application, and this one exists for auditing and study.
``save_draft`` therefore refuses unconditionally, and no tool calls it.

The guards below are kept deliberately rather than deleted. They are the
record of what this site permits and why — in particular that saving a Sales
Invoice submits it and transmits it to AGT — and they are what a future write
capability would have to satisfy. Flip ``WRITES_ENABLED`` and wire a tool to
``save_draft`` to revive it.

Original notes:

Three layers, in order of authority:

1. A hard deny list in code. Configuration cannot override it.
2. A derived deny list: any DocType whose ``before_save``/``before_insert``
   hooks mention submitting is refused, because on this site saving such a
   document submits it. That is how Sales Invoice behaves — ``saft_xml`` sets
   ``docstatus = 1`` before insert, and submission transmits the invoice to
   AGT. Deriving it means a future app that adds the same pattern is refused
   automatically rather than quietly allowed.
3. Frappe's own create permission for the user.

The assistant never submits anything, on any DocType.
"""

import json

import frappe

# Refused whatever the hooks or configuration say.
# Every write path is off. Nothing in the app calls save_draft.
WRITES_ENABLED = False

HARD_DENY = {
    "Sales Invoice",       # saving submits it and transmits to AGT
    "POS Invoice",
    "Payment Entry",
    "Journal Entry",
    "Stock Entry",
    "Stock Reconciliation",
    "Salary Slip", "Isoft Salary Slip", "Payroll Entry",
    "User", "Role", "Custom Script", "Server Script", "Property Setter",
}

# Allowed to be drafted, subject to the derived check and permissions.
DRAFTABLE = {
    "Quotation",
    "Sales Order",
    "Material Request",
}

SUSPICIOUS = ("submit", "registar", "transmit", "enqueue_registar")


def _hooks_force_submit(doctype):
    """True when merely saving this DocType can submit it."""
    events = (frappe.get_hooks("doc_events") or {}).get(doctype) or {}
    for event in ("before_save", "before_insert", "before_validate", "after_insert"):
        handlers = events.get(event) or []
        if isinstance(handlers, str):
            handlers = [handlers]
        for h in handlers:
            if any(token in str(h).lower() for token in SUSPICIOUS):
                return str(h)
    return None


def why_blocked(doctype):
    """Human-readable reason, or None when drafting is allowed."""
    if doctype in HARD_DENY:
        return "%s is on the assistant's permanent deny list." % doctype
    if doctype not in DRAFTABLE:
        return ("%s is not in the set of documents the assistant may draft (%s)."
                % (doctype, ", ".join(sorted(DRAFTABLE))))
    handler = _hooks_force_submit(doctype)
    if handler:
        return ("Saving a %s on this site runs %s, which can submit it. "
                "The assistant will not create one." % (doctype, handler))
    return None


def assert_draftable(doctype):
    reason = why_blocked(doctype)
    if reason:
        frappe.throw(reason, frappe.PermissionError)
    if not frappe.has_permission(doctype, "create"):
        frappe.throw("You do not have permission to create a %s." % doctype,
                     frappe.PermissionError)


def save_draft(doc):
    """Disabled. Would insert as a draft and prove it stayed one.

    The check after insert is the point: a hook could submit the document
    during save, and the only honest way to know is to look at what was
    actually stored.
    """
    if not WRITES_ENABLED:
        frappe.throw(
            "The assistant does not create or change documents. Create the %s in "
            "ERPNext, or in the application that owns that step."
            % doc.doctype,
            frappe.PermissionError,
        )

    assert_draftable(doc.doctype)

    doc.docstatus = 0
    doc.flags.ignore_permissions = False
    doc.insert()

    stored = frappe.db.get_value(doc.doctype, doc.name, "docstatus")
    if int(stored or 0) != 0:
        # Undo rather than leave a submitted document the user never approved.
        frappe.db.rollback()
        frappe.throw(
            "Saving that %s submitted it (docstatus %s). The change has been "
            "rolled back and the assistant will not create this document type."
            % (doc.doctype, stored),
            frappe.PermissionError,
        )
    return doc


def log_action(action, doctype, docname, before=None, after=None, detail=None):
    """Audit row for a write. Committed so it survives any caller."""
    try:
        frappe.get_doc({
            "doctype": "Isoft AI Action Log",
            "action": action,
            "ref_doctype": doctype,
            "ref_name": docname,
            "before_json": json.dumps(before, default=str, ensure_ascii=False)[:5000] if before else "",
            "after_json": json.dumps(after, default=str, ensure_ascii=False)[:5000] if after else "",
            "detail": (detail or "")[:2000],
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        from isoft_business_ai.ai.log import safe_log

        safe_log("warning", "could not write action log for %s %s" % (doctype, docname),
                 exc_info=True)
