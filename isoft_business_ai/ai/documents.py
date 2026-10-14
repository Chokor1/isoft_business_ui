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
from frappe import _

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

    if doctype:
        # The caller may have typed "cliente" or "Armazém"; resolve it to the
        # real doctype before filtering on it.
        doctype = resolve_doctype(doctype) or doctype
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
    return ["Customer", "Supplier", "Item", "Account", "Warehouse",
            "Quotation", "Sales Order", "Sales Invoice", "Delivery Note",
            "Purchase Order", "Purchase Invoice", "Purchase Receipt",
            "Material Request", "Stock Entry", "Payment Entry", "Journal Entry"]


# ----------------------------------------------------- doctype lookup for @

# A short list that should lead the suggestions, because they are what people
# actually mention. Everything else the site has still appears, ranked after.
COMMON_DOCTYPES = [
    "Customer", "Supplier", "Item", "Quotation", "Sales Order", "Sales Invoice",
    "Delivery Note", "Purchase Order", "Purchase Invoice", "Purchase Receipt",
    "Payment Entry", "Journal Entry", "Stock Entry", "Material Request",
    "Warehouse", "Account", "Employee", "Project", "Lead", "Opportunity",
]


def _normalise(text):
    """Lowercase and strip accents, so 'armazem' finds 'Armazém'."""
    text = (text or "").lower().strip()
    try:
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFD", text)
                       if unicodedata.category(c) != "Mn")
    except Exception:
        return text


# The desk may be in English while the people using it think in Portuguese, so
# every doctype is matchable in both whatever the account is set to.
SECOND_LANGUAGE = "pt"


def _second_language():
    """The Portuguese dictionary, keyed by the English source string.

    Loaded straight from the translation files rather than through
    _(name, lang="pt"): in this version of Frappe, get_full_dict() returns
    whatever dictionary the request already cached and ignores the language it
    was asked for, so inside an English session that call quietly hands back
    English and every Portuguese term stops matching.
    """
    try:
        from frappe.translate import load_lang

        return load_lang(SECOND_LANGUAGE) or {}
    except Exception:
        return {}


def _match_terms(*names):
    """Every spelling of one doctype a person might type."""
    terms = []
    for n in names:
        n = _normalise(n)
        if n and n not in terms:
            terms.append(n)
    return terms


def _catalogue():
    """Every mentionable doctype, named in both languages. Cached per language.

    Built once per desk language rather than per keystroke: the list is 280
    rows and the translation lookup behind each label is not free. `bench
    migrate` clears it, which is the only time the set can change.
    """
    lang = frappe.local.lang or "en"

    def build():
        out = []
        second = _second_language()
        rows = frappe.get_all("DocType", fields=["name"],
                              filters={"istable": 0, "issingle": 0},
                              limit_page_length=0)
        for r in rows:
            name = r["name"]
            if not is_business_doctype(name):
                continue
            label = _(name)
            out.append({
                "doctype": name,
                "label": label,
                "terms": _match_terms(name, label),
                "alt": [t for t in _match_terms(second.get(name))
                        if t not in _match_terms(name, label)],
                "common": 1 if name in COMMON_DOCTYPES else 0,
            })
        out.sort(key=lambda d: (-d["common"], d["label"]))
        return out

    return frappe.cache().get_value("ibai_mention_catalogue:" + lang, build) or []


def _business_doctypes():
    """Every doctype a user could sensibly mention."""
    return [d["doctype"] for d in _catalogue()]


def _rank(terms, needle):
    """How well a doctype matches what was typed; None if it does not.

    Only prefixes count - of the whole name, or of a word inside it. Matching a
    needle found anywhere at all is what made these suggestions useless: "cu"
    offered Loan Security Pledge, and "su" offered nothing a buyer wanted.
    """
    best = None
    for term in terms:
        if term == needle:
            rank = 0
        elif term.startswith(needle):
            rank = 1
        elif any(word.startswith(needle) for word in term.split()):
            rank = 2
        else:
            continue
        if best is None or rank < best:
            best = rank
    return best


def _rank_entry(entry, needle):
    """A doctype's match tier, its own language preferred over the other one.

    A Portuguese spelling still matches inside an English desk, but one tier
    lower, so an English user typing "cu" is offered Customer and Customs
    Tariff Number before Cost Center - which only matches because "custo"
    begins that way.
    """
    rank = _rank(entry.get("terms") or [], needle)
    if rank is not None:
        return rank
    rank = _rank(entry.get("alt") or [], needle)
    return None if rank is None else rank + 1


def _score(rank, common):
    """Two orders of preference flattened into one sort key.

    A better match always wins, and between equal matches the twenty doctypes
    people actually mention come first - so "account" leads with Account, not
    with Accounting Dimension Filter.
    """
    return rank * 2 + (0 if common else 1)


def search_doctypes(term, limit=8):
    """Doctypes matching what has been typed, in the user's own language."""
    needle = _normalise(term)
    hits = []
    for d in _catalogue():
        if not frappe.has_permission(d["doctype"], "read"):
            continue
        rank = _rank_entry(d, needle) if needle else 0
        if rank is None:
            continue
        hits.append((_score(rank, d["common"]), d["label"], d["doctype"]))

    hits.sort()
    return [{"doctype": dt, "label": label} for _s, label, dt in hits[:limit]]


def mention_catalogue():
    """The whole mentionable catalogue, for matching in the browser.

    Sent once per page instead of a round trip per keystroke, which is what
    lets a bare "su" offer Supplier before the word is finished. It carries the
    match terms, so Portuguese works without the browser knowing any
    Portuguese; the permission filter is applied here, not there.
    """
    return [{"doctype": d["doctype"], "label": d["label"],
             "terms": d["terms"], "alt": d["alt"], "common": d["common"]}
            for d in _catalogue() if frappe.has_permission(d["doctype"], "read")]


def resolve_doctype(text):
    """Turn whatever was typed before the @ or the colon into a real doctype."""
    needle = _normalise(text)
    if not needle:
        return None
    best = None
    for d in _catalogue():
        rank = _rank_entry(d, needle)
        if rank is None:
            continue
        key = (_score(rank, d["common"]), d["label"])
        if best is None or key < best[0]:
            best = (key, d["doctype"])
    return best[1] if best else None


def find_elsewhere(name, exclude=None, limit=4):
    """Which other doctypes hold a record with this exact name.

    A mention of the wrong type - "@[Customer:UNICOM, LDA]" for a record that is
    actually a Supplier - would otherwise come back as a flat "not found" and
    the question would die there. Naming the right type turns it into a
    correction the assistant can act on.
    """
    out = []
    for doctype in _business_doctypes():
        if doctype == exclude or not frappe.has_permission(doctype, "read"):
            continue
        try:
            if frappe.db.exists(doctype, name):
                out.append({"doctype": doctype, "label": _(doctype)})
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out
