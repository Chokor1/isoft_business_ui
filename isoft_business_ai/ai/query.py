"""The single door every tool goes through to reach the database.

Tools never call ``frappe.db.sql`` and never build a query string. They call
:func:`fetch`, which applies the guards, runs the query through
``frappe.get_list`` (so Frappe's permission and User Permission layers apply),
caps the row count, and records a human-readable provenance line.
"""

import time

import frappe
from frappe.utils import flt

from isoft_business_ai.ai.registry import MAX_ROWS
from isoft_business_ai.ai.log import safe_log
from isoft_business_ai.ai.security import check_fields, guard_doctypes

# Slow-query warning threshold, in seconds.
SLOW_QUERY_SECONDS = 5.0


# Reference data — a chart of accounts, a warehouse list, a grouped aggregate —
# is bounded by configuration rather than by transaction volume, and truncating
# it silently corrupts whatever is built on top. MAX_ROWS protects the browser
# and the token bill from long *result* lists; it is the wrong instrument here.
MAX_REFERENCE_ROWS = 10000


def fetch_reference(doctype, fields, filters=None, group_by=None, order_by=None,
                    or_filters=None):
    """Read bounded reference data without the display row cap.

    Use only where the row count is set by configuration (accounts, warehouses)
    or by a GROUP BY over such a set. Never for a list of documents.
    """
    return fetch(doctype, fields, filters=filters, group_by=group_by,
                 order_by=order_by, or_filters=or_filters,
                 limit=MAX_REFERENCE_ROWS, _reference=True)


def fetch(doctype, fields, filters=None, group_by=None, order_by=None,
          limit=None, extra_doctypes=None, or_filters=None, _reference=False):
    """Run one permission-aware read.

    ``extra_doctypes`` names any child or joined DocType the field list reaches
    into, so read permission is checked on those too.
    """
    guard_doctypes([doctype] + list(extra_doctypes or []))
    check_fields(fields)

    ceiling = MAX_REFERENCE_ROWS if _reference else MAX_ROWS
    limit = min(int(limit or ceiling), ceiling)

    started = time.time()
    rows = frappe.get_list(
        doctype,
        fields=fields,
        filters=filters or {},
        or_filters=or_filters or [],
        group_by=group_by,
        order_by=order_by,
        limit_page_length=limit,
    )
    elapsed = time.time() - started

    if elapsed > SLOW_QUERY_SECONDS:
        safe_log("warning", "slow tool query %.1fs on %s (%s rows)"
                 % (elapsed, doctype, len(rows)))

    return [dict(r) for r in rows]


def describe(doctype, company, from_date=None, to_date=None, extra=None):
    """Build the provenance line the user sees under every answer."""
    bits = [doctype]
    if company:
        bits.append("company: %s" % company)
    if from_date and to_date:
        bits.append("%s to %s" % (from_date, to_date))
    elif from_date:
        bits.append("from %s" % from_date)
    elif to_date:
        bits.append("until %s" % to_date)
    for k, v in sorted((extra or {}).items()):
        if v not in (None, "", []):
            bits.append("%s: %s" % (k, v))
    return " | ".join(bits)


def submitted(filters=None):
    """Filters for submitted documents only.

    Nearly every wrong number in an ERPNext report traces back to forgetting
    this, so it is a named helper rather than a literal repeated in each tool.
    """
    out = {"docstatus": 1}
    out.update(filters or {})
    return out


def date_range(field, from_date, to_date):
    return {field: ["between", [from_date, to_date]]}


def grand_total(doctype, filters, value_field, count_field="name",
                group_field=None, extra_doctypes=None, or_filters=None):
    """One uncapped aggregate over everything the filters match.

    The point is that it does NOT depend on the row cap. A tool that lists the
    50 largest customers and lets the model add those 50 up reports a total for
    50 customers while calling it the total. Worse, the model may simply add
    them up wrong: in testing, the assistant summed eleven supplier rows by hand
    and reported a total that was out by ten million.

    So every tool that returns a grouped money breakdown hands back its own
    total from here, and the prompt forbids the model from adding rows itself.
    """
    fields = ["sum(%s) as total" % value_field, "count(%s) as n" % count_field]
    if group_field:
        fields.append("count(distinct %s) as groups" % group_field)
    rows = fetch(
        doctype,
        fields=fields,
        filters=filters,
        or_filters=or_filters,
        extra_doctypes=extra_doctypes,
        limit=1,
    )
    if not rows:
        return 0.0, 0, 0
    r = rows[0]
    return (flt(r.get("total")), int(r.get("n") or 0),
            int(r.get("groups") or 0) if group_field else 0)


def page_share(rows, value_key, total):
    """What the listed page itself comes to, and its share of the whole.

    Questions like "what share comes from the top five customers" otherwise
    force the model to add the rows and divide, and it gets that wrong: on a
    live site it reported a share two hundredths of a percent off the true one.
    Both numbers are given here so the answer is a quotation, not a sum.
    """
    if not rows:
        return ""
    shown = sum(flt(r.get(value_key)) for r in rows)
    out = "The %d rows listed come to %s" % (len(rows), round(shown, 2))
    if total:
        out += ", which is %s%% of that grand total" % round(shown / flt(total) * 100, 2)
    return out + "; both figures are already worked out, so quote them rather than adding up."


def total_note(total, documents, groups, document_noun, group_noun,
               rows=None, value_key=None):
    """The sentence every grouped tool ends with, worded so the two counts
    cannot be mistaken for each other."""
    if groups:
        scope = "across %d %s in %d %s" % (groups, group_noun, documents, document_noun)
    else:
        scope = "across %d %s" % (documents, document_noun)
    note = ("Grand total over everything these filters match: %s %s. "
            "The table is a capped page of that set - do not add its rows up yourself."
            % (round(total, 2), scope))
    if rows is not None and value_key:
        extra = page_share(rows, value_key, total)
        if extra:
            note += " " + extra
    return note


def grouped_total(doctype, fields, filters, group_by, value_key,
                  extra_doctypes=None, or_filters=None):
    """Total a grouped aggregate the display page had to cap.

    Used where the figure lives on a child table and a single SUM cannot be
    expressed: Frappe's query builder only joins a child table when the select
    list names one of its plain columns, so an aggregate-only select over
    `tabSales Invoice Item` never gets its FROM clause and fails outright.

    Reading every group uncapped and adding them here is exact as long as the
    group count stays under MAX_REFERENCE_ROWS, which is why the caller is
    handed the count back and says so when it is reached.
    """
    rows = fetch(doctype, fields=fields, filters=filters, or_filters=or_filters,
                 group_by=group_by, extra_doctypes=extra_doctypes,
                 limit=MAX_REFERENCE_ROWS, _reference=True)
    total = sum(flt(r.get(value_key)) for r in rows)
    complete = len(rows) < MAX_REFERENCE_ROWS
    return total, len(rows), complete
