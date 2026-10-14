"""Generic document access.

The 15 hand-written tools answer aggregate questions. This module answers
"what is in *this* document" for any business DocType on the site — there are
274 of them — without a tool per type.

Two things keep it safe and affordable: every read goes through Frappe's
permission check for that specific document, and the summary is built from the
DocType's own metadata rather than dumping the record, so a 200-field invoice
costs a few hundred tokens instead of several thousand.
"""

import frappe

from isoft_business_ai.ai.security import BLOCKED_DOCTYPES, BLOCKED_FIELDS

# Modules whose documents are business records a user might ask about.
BUSINESS_MODULES = {
    "Accounts", "Selling", "Buying", "Stock", "Manufacturing", "CRM",
    "Projects", "Assets", "Support", "Quality Management", "Maintenance",
    "Isoft Invenza", "Isoft Location Manager",
}

# Never reachable through mentions, whatever permissions say.
EXTRA_BLOCKED = {
    "Salary Slip", "Isoft Salary Slip", "Salary Structure", "Employee",
    "Payroll Entry", "Employee Tax Exemption Declaration", "Additional Salary",
    "Employee Grade", "Retention Bonus", "Employee Incentive",
}

# Fieldtypes that are either enormous or meaningless out of context.
SKIP_FIELDTYPES = {
    "Section Break", "Column Break", "Tab Break", "HTML", "Button", "Image",
    "Attach", "Attach Image", "Text Editor", "Code", "Signature", "Fold",
    "Heading", "Barcode", "Geolocation", "HTML Editor", "Markdown Editor",
}

MAX_HEADER_FIELDS = 18
MAX_CHILD_ROWS = 12
MAX_CHILD_COLS = 6
DOCSTATUS = {0: "Draft", 1: "Submitted", 2: "Cancelled"}


def is_business_doctype(doctype):
    """A document a user could sensibly mention."""
    if not doctype or doctype in BLOCKED_DOCTYPES or doctype in EXTRA_BLOCKED:
        return False
    try:
        meta = frappe.get_meta(doctype)
    except Exception:
        return False
    if meta.istable or meta.issingle:
        return False
    return bool(meta.is_submittable) or meta.module in BUSINESS_MODULES


def _is_safe_field(df):
    if df.fieldtype in SKIP_FIELDTYPES or df.hidden:
        return False
    lowered = (df.fieldname or "").lower()
    return not any(b in lowered for b in BLOCKED_FIELDS)


def _header_fields(meta):
    """The fields worth showing, in the order the form shows them.

    Preference goes to what the list view already considers identifying, then
    to money, dates and links — which is what business questions turn on.
    """
    preferred, other = [], []
    for df in meta.fields:
        if not _is_safe_field(df):
            continue
        if df.in_list_view or df.bold or df.reqd:
            preferred.append(df)
        elif df.fieldtype in ("Currency", "Date", "Datetime", "Link", "Select",
                              "Int", "Float", "Percent", "Check", "Data"):
            other.append(df)
    return (preferred + other)[:MAX_HEADER_FIELDS]


def summarise(doctype, name, child_rows=MAX_CHILD_ROWS):
    """A compact, permission-checked view of one document."""
    if not is_business_doctype(doctype):
        frappe.throw("%s is not a business document this assistant can open." % doctype)

    if not frappe.has_permission(doctype, "read", doc=name):
        frappe.throw("You do not have permission to read %s %s." % (doctype, name),
                     frappe.PermissionError)

    doc = frappe.get_doc(doctype, name)
    meta = frappe.get_meta(doctype)

    header = {}
    for df in _header_fields(meta):
        value = doc.get(df.fieldname)
        if value in (None, "", 0, []) and df.fieldtype != "Check":
            continue
        header[df.label or df.fieldname] = value

    out = {
        "doctype": doctype,
        "name": doc.name,
        "status": doc.get("status") or DOCSTATUS.get(int(doc.get("docstatus") or 0)),
        "docstatus": DOCSTATUS.get(int(doc.get("docstatus") or 0)),
        "fields": header,
    }

    # Only the first child table: it is the one that carries the lines.
    table_fields = [f for f in meta.fields if f.fieldtype == "Table"]
    if table_fields:
        tf = table_fields[0]
        rows = doc.get(tf.fieldname) or []
        child_meta = frappe.get_meta(tf.options)
        cols = [df.fieldname for df in child_meta.fields
                if df.in_list_view and _is_safe_field(df)][:MAX_CHILD_COLS]
        if not cols:
            cols = [df.fieldname for df in child_meta.fields
                    if _is_safe_field(df) and df.fieldtype in
                    ("Data", "Link", "Currency", "Float", "Int")][:MAX_CHILD_COLS]
        out["lines"] = {
            "table": tf.options,
            "columns": cols,
            "rows": [[r.get(c) for c in cols] for r in rows[:child_rows]],
            "row_count": len(rows),
        }
        if len(rows) > child_rows:
            out["lines"]["note"] = (
                "Showing %d of %d lines." % (child_rows, len(rows)))

    return out


def search(query, doctype=None, limit=10):
    """Find documents to mention. Permission-filtered by get_list."""
    query = (query or "").strip()
    results = []

    doctypes = [doctype] if doctype else _likely_doctypes(query)
    for dt in doctypes:
        if len(results) >= limit * 2:
            break
        if not is_business_doctype(dt):
            continue
        try:
            meta = frappe.get_meta(dt)
            fields = ["name"]
            title = meta.title_field if meta.title_field != "name" else None
            if title and meta.get_field(title):
                fields.append(title)
            or_filters = []
            if query:
                like = "%" + query + "%"
                or_filters.append(["name", "like", like])
                # Also by who it is for: a quotation is remembered by the
                # customer on it, not by its naming series.
                if title and meta.get_field(title):
                    or_filters.append([title, "like", like])
            rows = frappe.get_list(
                dt,
                fields=fields,
                or_filters=or_filters,
                order_by="modified desc",
                limit_page_length=limit,
            )
        except Exception:
            continue
        for r in rows:
            label = r.get(title) if title else None
            results.append({
                "doctype": dt,
                "name": r["name"],
                "label": label if label and label != r["name"] else "",
            })
    return results[: limit * 2]


def _likely_doctypes(query):
    """Which doctypes a bare query could belong to, most likely first.

    Parties and items lead: people type a customer or item name they remember
    far more often than a document code, and a mentioned customer is what most
    of the tools actually take as a parameter. Transactions follow, found by
    their naming series ("PP ALV2026/7") or by who they are for.
    """
    return ["Customer", "Supplier", "Item",
            "Quotation", "Sales Order", "Sales Invoice", "Delivery Note",
            "Purchase Order", "Purchase Invoice", "Purchase Receipt",
            "Material Request", "Stock Entry", "Payment Entry", "Journal Entry"]
