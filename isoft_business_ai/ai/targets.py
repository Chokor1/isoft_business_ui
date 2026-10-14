"""Targets and the gap to them.

The assistant could already answer "how much did we sell". It could not answer
"am I going to make it", which is the only question a manager actually has. A
target turns a number into a position: how far, how fast, and whether the
current pace gets there.

Everything here is read-only and permission-aware; the metrics go through the
same ``fetch`` door as every other tool.
"""

from frappe.utils import date_diff, flt, getdate, nowdate

import frappe

from isoft_business_ai.ai.query import fetch, submitted

# metric -> (doctype, amount field, date field, extra filters, label)
METRICS = {
    "sales": ("Sales Invoice", "base_grand_total", "posting_date", {}, "Sales invoiced"),
    "purchases": ("Purchase Invoice", "base_grand_total", "posting_date", {}, "Purchases invoiced"),
    "collections": ("Payment Entry", "base_paid_amount", "posting_date",
                    {"payment_type": "Receive"}, "Cash collected"),
}


def measure(metric, company, from_date, to_date):
    """Actual value of one metric over a period."""
    spec = METRICS.get(metric)
    if not spec:
        frappe.throw("Unknown metric %r. Use one of: %s" % (metric, ", ".join(METRICS)))
    doctype, amount_field, date_field, extra, _label = spec

    filters = submitted({"company": company})
    filters.update(extra)
    filters[date_field] = ["between", [from_date, to_date]]

    rows = fetch(doctype, fields=["sum(%s) as total" % amount_field,
                                  "count(name) as documents"], filters=filters)
    row = rows[0] if rows else {}
    return flt(row.get("total")), int(row.get("documents") or 0)


def progress(target, as_on=None):
    """Where one target stands, and whether the current pace reaches it.

    The projection is deliberately naive — actual divided by elapsed days,
    extended over the period. A manager needs the arithmetic to be obvious
    enough to argue with, not a model they have to trust.
    """
    as_on = getdate(as_on or nowdate())
    start, end = getdate(target.period_start), getdate(target.period_end)

    actual, documents = measure(target.metric, target.company, start,
                                min(as_on, end))
    goal = flt(target.target_amount)

    total_days = max(1, date_diff(end, start) + 1)
    elapsed = max(0, min(total_days, date_diff(as_on, start) + 1))
    remaining = max(0, total_days - elapsed)

    pct = (actual / goal * 100) if goal else None
    pace = (actual / elapsed) if elapsed else 0.0
    projected = pace * total_days
    gap = goal - actual
    needed_per_day = (gap / remaining) if remaining > 0 and gap > 0 else None

    if gap <= 0:
        verdict = "met"
    elif remaining == 0:
        verdict = "missed"
    elif projected >= goal:
        verdict = "on track"
    else:
        verdict = "behind"

    return {
        "target": target.name,
        "title": target.title,
        "metric": target.metric,
        "label": METRICS[target.metric][4],
        "company": target.company,
        "period": "%s to %s" % (start, end),
        "goal": goal,
        "actual": actual,
        "documents": documents,
        "pct": round(pct, 1) if pct is not None else None,
        "gap": round(gap, 2),
        "days_elapsed": elapsed,
        "days_remaining": remaining,
        "run_rate_per_day": round(pace, 2),
        "projected_at_this_pace": round(projected, 2),
        "needed_per_day_to_close": round(needed_per_day, 2) if needed_per_day else None,
        "verdict": verdict,
    }


def active_targets(company=None, as_on=None):
    """Targets whose period covers ``as_on``, for companies the user may see."""
    as_on = getdate(as_on or nowdate())
    filters = {"active": 1,
               "period_start": ["<=", as_on],
               "period_end": [">=", as_on]}
    if company:
        filters["company"] = company
    names = fetch("Isoft Business Target", fields=["name"], filters=filters,
                  order_by="period_end asc", limit=50)
    return [frappe.get_doc("Isoft Business Target", n["name"]) for n in names]
