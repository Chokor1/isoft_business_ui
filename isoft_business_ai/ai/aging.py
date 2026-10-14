"""Aging buckets computed in SQL, not by summing a capped page of rows.

The obvious implementation fetches open invoices, caps the fetch, and adds them
up in Python. It is correct right up to the day the customer crosses the cap,
and then it silently under-reports. So each bucket is its own grouped aggregate
over *all* matching invoices, and the grand total is a separate uncapped
aggregate that stays right even when the per-party list is truncated.
"""

from frappe.utils import add_days, flt

from isoft_business_ai.ai.query import fetch, submitted

BUCKETS = [
    ("nao_vencido", "Not due"),
    ("d1_30", "1-30 days"),
    ("d31_60", "31-60 days"),
    ("d61_90", "61-90 days"),
    ("d90_mais", "Over 90 days"),
]

# Maximum distinct parties listed. The grand total does not depend on this.
MAX_PARTIES = 500


def _bucket_filters(bucket, as_on):
    """Filters selecting one aging bucket by due_date."""
    if bucket == "nao_vencido":
        return {}, [["due_date", ">=", as_on], ["due_date", "is", "not set"]]
    if bucket == "d1_30":
        return {"due_date": ["between", [add_days(as_on, -30), add_days(as_on, -1)]]}, []
    if bucket == "d31_60":
        return {"due_date": ["between", [add_days(as_on, -60), add_days(as_on, -31)]]}, []
    if bucket == "d61_90":
        return {"due_date": ["between", [add_days(as_on, -90), add_days(as_on, -61)]]}, []
    return {"due_date": ["<", add_days(as_on, -90)]}, []


def build_aging(doctype, party_field, party_name_field, company, as_on,
                party=None, apenas_vencido=False, limite=50, ascendente=False):
    """Return (rows, totals) for a receivables- or payables-style aging report."""
    base = submitted({"company": company, "outstanding_amount": [">", 0]})
    if party:
        base[party_field] = party

    buckets = [b for b in BUCKETS if not (apenas_vencido and b[0] == "nao_vencido")]

    by_party = {}
    for key, _label in buckets:
        extra_filters, or_filters = _bucket_filters(key, as_on)
        filters = dict(base)
        filters.update(extra_filters)

        rows = fetch(
            doctype,
            fields=[
                "%s as party" % party_field,
                "%s as party_name" % party_name_field,
                "sum(outstanding_amount) as valor",
                "count(name) as facturas",
            ],
            filters=filters,
            or_filters=or_filters,
            group_by=party_field,
            order_by="valor desc",
            limit=MAX_PARTIES,
        )
        for row in rows:
            entry = by_party.setdefault(row["party"], {
                "party": row["party"],
                "party_name": row.get("party_name"),
                "total": 0.0,
                "facturas": 0,
            })
            for bkey, _l in BUCKETS:
                entry.setdefault(bkey, 0.0)
            entry[key] = flt(row.get("valor"))
            entry["total"] += flt(row.get("valor"))
            entry["facturas"] += int(row.get("facturas") or 0)

    ordered = sorted(by_party.values(), key=lambda r: r["total"], reverse=not ascendente)
    listed = ordered[: (limite or 50)]

    # Uncapped grand total, independent of how many parties are listed.
    grand = {"total": 0.0, "facturas": 0}
    for key, _label in buckets:
        extra_filters, or_filters = _bucket_filters(key, as_on)
        filters = dict(base)
        filters.update(extra_filters)
        agg = fetch(
            doctype,
            fields=["sum(outstanding_amount) as valor", "count(name) as facturas"],
            filters=filters,
            or_filters=or_filters,
        )
        agg = agg[0] if agg else {}
        grand[key] = flt(agg.get("valor"))
        grand["total"] += flt(agg.get("valor"))
        grand["facturas"] += int(agg.get("facturas") or 0)

    grand["parties"] = len(ordered)
    grand["listed"] = len(listed)
    return listed, grand
