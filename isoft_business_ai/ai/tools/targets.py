"""Targets and alerts as tools.

These are what turn the assistant from a reporting tool into something a
manager can steer by: where a target stands, and what is worth looking at
without being asked.
"""

from isoft_business_ai.ai import alerts as alerts_engine
from isoft_business_ai.ai import targets as engine
from isoft_business_ai.ai.formatting import currency, integer, number, text
from isoft_business_ai.ai.query import describe
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="target_progress",
    description=(
        "Where the company's targets stand: actual against goal, the gap, days left, the "
        "current daily run rate, where that pace lands, and what per day would close it. "
        "Use for 'am I going to hit my target', 'how are we doing against plan', 'what is "
        "the gap', 'what do I need per day'."
    ),
    params={
        "company": Param.text("Company.", optional=True),
        "as_on": Param.date("Measure as at this date. Omit for today.", optional=True),
    },
    doctypes=["Isoft Business Target"],
    group="targets",
)
def target_progress(company=None, as_on=None):
    company = resolve_company(company)
    targets = engine.active_targets(company, as_on)

    if not targets:
        return ToolResult(
            columns=[text("title", "Target")],
            rows=[],
            source=describe("Isoft Business Target", company, extra={"as at": as_on or "today"}),
            note=("No active target covers this date. Tell the user no target is set and "
                  "that one can be created under Isoft Business Target — metric, period "
                  "and amount."),
        )

    rows = [engine.progress(t, as_on) for t in targets]
    return ToolResult(
        columns=[
            text("title", "Target"),
            text("label", "Metric"),
            currency("goal", "Goal"),
            currency("actual", "Actual"),
            number("pct", "% of goal"),
            currency("gap", "Gap"),
            integer("days_remaining", "Days left"),
            currency("run_rate_per_day", "Per day so far"),
            currency("needed_per_day_to_close", "Per day needed"),
            currency("projected_at_this_pace", "Lands at"),
            text("verdict", "Verdict"),
        ],
        rows=rows,
        source=describe("Isoft Business Target", company, extra={"as at": as_on or "today"}),
        note=("The projection is actual divided by elapsed days, extended over the whole "
              "period. State the verdict and the per-day figure needed, not just the total."),
    )


@ai_tool(
    name="business_alerts",
    description=(
        "What is worth the manager's attention right now, without being asked: a broken "
        "sales trend, debt concentrated on one customer, receivables aged past 90 days, "
        "collections that have stalled, and any target running behind. Use for 'how is "
        "the business', 'anything I should know', 'what should I look at', or to open a "
        "conversation when the user has not asked anything specific."
    ),
    params={"company": Param.text("Company.", optional=True)},
    doctypes=["Sales Invoice", "Payment Entry"],
    group="targets",
)
def business_alerts(company=None):
    company = resolve_company(company)
    found = alerts_engine.run(company)

    if not found:
        return ToolResult(
            columns=[text("title", "Signal")],
            rows=[],
            source=describe("Sales Invoice / Payment Entry / targets", company),
            note="Nothing crossed a threshold. Say so plainly rather than inventing concern.",
        )

    return ToolResult(
        columns=[
            text("severity", "Severity"),
            text("title", "Signal"),
            text("detail", "Detail"),
            text("ask", "Worth asking next"),
        ],
        rows=found,
        source=describe("Sales Invoice / Payment Entry / targets", company),
        note=("Thresholds are blunt on purpose and stated in each detail line. Lead with "
              "the most severe, and offer the follow-up question."),
    )


@ai_tool(
    name="gap_closers",
    description=(
        "What could actually close the gap on a target: for a sales target, the open "
        "quotations and orders not yet invoiced, largest first, with a running total "
        "showing how far down the list you must get. For a collections target, the "
        "overdue customers ranked the same way. Use for 'how do I close the gap', "
        "'what do I need to win', 'who should I chase', 'what gets me to my number'."
    ),
    params={
        "metric": Param.enum("Which target to close.", ["sales", "collections"]),
        "company": Param.text("Company.", optional=True),
        "gap": Param.text(
            "The amount to close. Omit to take it from the active target.", optional=True),
    },
    doctypes=["Quotation", "Sales Order", "Sales Invoice"],
    group="targets",
)
def gap_closers(metric, company=None, gap=None):
    from frappe.utils import flt, nowdate

    from isoft_business_ai.ai.query import fetch, submitted

    company = resolve_company(company)

    target_gap = flt(str(gap).replace(",", "")) if gap else 0.0
    source = "supplied"
    if not target_gap:
        for t in engine.active_targets(company):
            if t.metric == metric:
                p = engine.progress(t)
                target_gap = max(0.0, flt(p["gap"]))
                source = t.title
                break
    if not target_gap:
        return ToolResult(
            columns=[text("name", "Document")], rows=[],
            source=describe("targets", company),
            note=("No gap to close: either no active %s target exists or it is already "
                  "met. Ask the user for an amount if they want a list anyway." % metric))

    if metric == "sales":
        # Open demand: quoted or ordered, not yet invoiced.
        rows = []
        for doctype, label, amount in (("Sales Order", "Order", "base_grand_total"),
                                       ("Quotation", "Quotation", "base_grand_total")):
            filters = submitted({"company": company})
            if doctype == "Sales Order":
                filters["status"] = ["not in", ["Closed", "Completed"]]
            else:
                filters["status"] = ["not in", ["Lost", "Ordered", "Expired"]]
            for r in fetch(doctype,
                           fields=["name", "customer_name" if doctype == "Sales Order"
                                   else "party_name", amount + " as value"],
                           filters=filters, order_by="%s desc" % amount, limit=60):
                rows.append({
                    "kind": label,
                    "name": r["name"],
                    "party": (r.get("customer_name") or r.get("party_name") or "").strip(),
                    "value": flt(r["value"]),
                })
        rows.sort(key=lambda r: -r["value"])
        unit = "open demand"
    else:
        agg = fetch("Sales Invoice",
                    fields=["customer", "customer_name",
                            "sum(outstanding_amount) as value",
                            "count(name) as documents"],
                    filters=submitted({"company": company,
                                       "outstanding_amount": [">", 0],
                                       "due_date": ["<", nowdate()]}),
                    group_by="customer", order_by="value desc", limit=60)
        rows = [{"kind": "Overdue", "name": r["customer"],
                 "party": (r.get("customer_name") or "").strip(),
                 "value": flt(r["value"])} for r in agg]
        unit = "overdue balances"

    running = 0.0
    enough = None
    for i, r in enumerate(rows, start=1):
        running += r["value"]
        r["cumulative"] = round(running, 2)
        r["closes_gap"] = "YES" if running >= target_gap and enough is None else ""
        if running >= target_gap and enough is None:
            enough = i

    shown = rows[: max(1, (enough or len(rows)))][:25]
    note = ("Gap of %s from %s. " % (round(target_gap, 2), source))
    if enough:
        note += ("The top %d of %d %s reach it." % (enough, len(rows), unit))
    else:
        note += ("All %d %s together come to %s, which is %s short — the gap cannot be "
                 "closed from what is already in the pipeline."
                 % (len(rows), unit, round(running, 2), round(target_gap - running, 2)))

    return ToolResult(
        columns=[
            text("kind", "Type"),
            text("name", "Document"),
            text("party", "Customer"),
            currency("value", "Value"),
            currency("cumulative", "Running total"),
            text("closes_gap", "Closes gap"),
        ],
        rows=shown,
        source=describe("open %s" % unit, company, extra={"gap": round(target_gap, 2)}),
        note=note,
    )
