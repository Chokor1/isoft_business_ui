"""Signals a manager should be told without having to ask.

Everything else in this app is reactive: it answers the question put to it. A
manager who does not know which question to ask gets nothing. These checks look
at the shape of the business and name what stands out, each with the question to
ask next so the finding leads somewhere.

Thresholds are deliberately blunt and stated in the output. A manager can argue
with "down 40% against the previous three months"; they cannot argue with a
score.
"""

from frappe.utils import add_days, add_months, flt, getdate, nowdate

from isoft_business_ai.ai.query import fetch, submitted
from isoft_business_ai.ai.targets import active_targets, progress

# A month this far below the median of the previous three is worth saying out loud.
TREND_DROP_PCT = 40.0
# One customer holding more than this share of the debt is a concentration risk.
CONCENTRATION_PCT = 30.0
# Collections over the last quarter, as a share of what is outstanding.
COLLECTION_STALL_PCT = 5.0
# Share of outstanding sitting beyond 90 days.
OVERDUE_HEAVY_PCT = 50.0


def _monthly_sales(company, months=6):
    start = add_months(getdate(nowdate()).replace(day=1), -months)
    rows = fetch(
        "Sales Invoice",
        fields=["YEAR(posting_date) as y", "MONTH(posting_date) as m",
                "sum(base_grand_total) as total"],
        filters=submitted({"company": company,
                           "posting_date": [">=", start]}),
        group_by="YEAR(posting_date), MONTH(posting_date)",
        order_by="y asc, m asc",
    )
    return [{"period": "%04d-%02d" % (int(r["y"]), int(r["m"])),
             "total": flt(r["total"])} for r in rows]


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def check_sales_trend(company):
    series = _monthly_sales(company, months=6)
    # The current month is incomplete, so compare the last *finished* one.
    this_month = getdate(nowdate()).strftime("%Y-%m")
    finished = [p for p in series if p["period"] != this_month]
    if len(finished) < 4:
        return None

    latest = finished[-1]
    baseline = _median([p["total"] for p in finished[-4:-1]])
    if baseline <= 0:
        return None
    drop = (baseline - latest["total"]) / baseline * 100
    if drop < TREND_DROP_PCT:
        return None

    return {
        "severity": "high" if drop >= 80 else "medium",
        "kind": "trend",
        "title": "Sales fell %.0f%% in %s" % (drop, latest["period"]),
        "detail": ("%s invoiced %s against a median of %s over the previous three "
                   "months." % (latest["period"], round(latest["total"], 2),
                                round(baseline, 2))),
        "ask": "Show the monthly sales trend and the top customers for %s" % latest["period"],
    }


def _outstanding(company):
    rows = fetch("Sales Invoice",
                 fields=["customer", "customer_name",
                         "sum(outstanding_amount) as total"],
                 filters=submitted({"company": company,
                                    "outstanding_amount": [">", 0]}),
                 group_by="customer", order_by="total desc", limit=500)
    total = sum(flt(r["total"]) for r in rows)
    return rows, total


def check_concentration(company):
    rows, total = _outstanding(company)
    if not rows or total <= 0:
        return None
    top = rows[0]
    share = flt(top["total"]) / total * 100
    if share < CONCENTRATION_PCT:
        return None
    return {
        "severity": "high" if share >= 45 else "medium",
        "kind": "concentration",
        "title": "%.0f%% of the money owed sits with one customer" % share,
        "detail": ("%s owes %s of %s outstanding across %d customers."
                   % ((top.get("customer_name") or top["customer"]).strip(),
                      round(flt(top["total"]), 2), round(total, 2), len(rows))),
        "ask": "Show the statement for %s" % top["customer"],
    }


def check_overdue_weight(company, as_on=None):
    as_on = getdate(as_on or nowdate())
    _rows, total = _outstanding(company)
    if total <= 0:
        return None
    old = fetch("Sales Invoice", fields=["sum(outstanding_amount) as total"],
                filters=submitted({"company": company,
                                   "outstanding_amount": [">", 0],
                                   "due_date": ["<", add_days(as_on, -90)]}))
    aged = flt(old[0]["total"]) if old else 0.0
    share = aged / total * 100
    if share < OVERDUE_HEAVY_PCT:
        return None
    return {
        "severity": "high" if share >= 80 else "medium",
        "kind": "overdue",
        "title": "%.0f%% of receivables are more than 90 days overdue" % share,
        "detail": "%s of %s outstanding is beyond 90 days." % (round(aged, 2), round(total, 2)),
        "ask": "Which customers are more than 90 days overdue?",
    }


def check_collection_stall(company, as_on=None):
    as_on = getdate(as_on or nowdate())
    _rows, total = _outstanding(company)
    if total <= 0:
        return None
    got = fetch("Payment Entry", fields=["sum(base_paid_amount) as total",
                                         "count(name) as n"],
                filters=submitted({"company": company, "payment_type": "Receive",
                                   "posting_date": [">=", add_days(as_on, -90)]}))
    collected = flt(got[0]["total"]) if got else 0.0
    count = int(got[0]["n"]) if got else 0
    share = collected / total * 100
    if share >= COLLECTION_STALL_PCT:
        return None
    return {
        "severity": "high",
        "kind": "collection",
        "title": "Almost nothing collected in 90 days",
        "detail": ("%d payments totalling %s against %s outstanding — %.2f%% of the book."
                   % (count, round(collected, 2), round(total, 2), share)),
        "ask": "Who owes us the most, and how overdue is it?",
    }


def check_targets(company):
    out = []
    for target in active_targets(company):
        p = progress(target)
        if p["verdict"] in ("behind", "missed"):
            out.append({
                "severity": "high" if p["verdict"] == "missed" else "medium",
                "kind": "target",
                "title": "%s is %s" % (p["title"], p["verdict"]),
                "detail": ("%s of %s (%.0f%%) with %d days left. At the current pace "
                           "it reaches %s."
                           % (round(p["actual"], 2), round(p["goal"], 2), p["pct"] or 0,
                              p["days_remaining"], round(p["projected_at_this_pace"], 2))),
                "ask": "What would it take to close the gap on %s?" % p["title"],
            })
    return out


CHECKS = (check_sales_trend, check_concentration, check_overdue_weight,
          check_collection_stall)


def run(company):
    """Every signal worth raising, most severe first."""
    found = []
    for check in CHECKS:
        try:
            result = check(company)
        except Exception:
            # One failing check must not silence the rest.
            result = None
        if result:
            found.append(result)
    try:
        found.extend(check_targets(company))
    except Exception:
        pass

    order = {"high": 0, "medium": 1, "low": 2}
    found.sort(key=lambda a: order.get(a["severity"], 9))
    return found
