"""Stock movement and sales pipeline.

Both answer "how did we get here" rather than "where are we now": the existing
stock tools read the current balance, and the sales tools read what was already
invoiced. These read the movements and the demand that has not landed yet.
"""

from frappe.utils import flt, nowdate

from isoft_business_ai.ai.formatting import currency, integer, number, text
from isoft_business_ai.ai.query import describe, fetch, fetch_reference, submitted
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="stock_ledger",
    description=(
        "Stock movements over a period: every receipt, issue, transfer and adjustment for "
        "an item or warehouse, with the quantity after each one. Use for 'how did this "
        "stock change', 'where did these units go', 'movement history', 'why is the stock "
        "different'. For the current balance use stock_actual instead."
    ),
    params={
        "from_date": Param.date("Period start."),
        "to_date": Param.date("Period end."),
        "item_code": Param.text("Restrict to one item (exact code).", optional=True),
        "warehouse": Param.text("Restrict to one warehouse.", optional=True),
        "limite": Param.integer("Maximum movements. Default 200.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Stock Ledger Entry"],
    group="stock",
)
def stock_ledger(from_date, to_date, item_code=None, warehouse=None, limite=200, company=None):
    company = resolve_company(company)

    filters = {"is_cancelled": 0,
               "posting_date": ["between", [from_date, to_date]]}
    if item_code:
        filters["item_code"] = item_code
    if warehouse:
        filters["warehouse"] = warehouse
    else:
        # Stock Ledger Entry carries a company field, but scoping by the
        # company's own warehouses is the same answer and survives a site
        # where the field was never filled.
        houses = fetch_reference("Warehouse", fields=["name"],
                                 filters={"company": company, "is_group": 0})
        if not houses:
            return ToolResult(columns=[text("item_code", "Item")], rows=[],
                              source=describe("Stock Ledger Entry", company),
                              note="%s has no warehouses configured." % company)
        filters["warehouse"] = ["in", [h["name"] for h in houses]]

    rows = fetch("Stock Ledger Entry",
                 fields=["posting_date", "item_code", "warehouse", "actual_qty",
                         "qty_after_transaction", "valuation_rate", "stock_value",
                         "voucher_type", "voucher_no"],
                 filters=filters,
                 order_by="posting_date asc, posting_time asc, creation asc",
                 limit=min(int(limite or 200), 500))

    moved_in = sum(flt(r["actual_qty"]) for r in rows if flt(r["actual_qty"]) > 0)
    moved_out = sum(flt(r["actual_qty"]) for r in rows if flt(r["actual_qty"]) < 0)

    return ToolResult(
        columns=[text("posting_date", "Date"), text("item_code", "Item"),
                 text("warehouse", "Warehouse"), text("voucher_type", "Type"),
                 text("voucher_no", "Document"), number("actual_qty", "Movement"),
                 number("qty_after_transaction", "Balance after"),
                 currency("valuation_rate", "Rate")],
        rows=rows,
        source=describe("Stock Ledger Entry (not cancelled)", company, from_date, to_date,
                        {"item": item_code, "warehouse": warehouse}),
        filters_applied={"item_code": item_code, "warehouse": warehouse},
        header={"Movements": len(rows), "Units in": round(moved_in, 2),
                "Units out": round(moved_out, 2),
                "Net": round(moved_in + moved_out, 2)},
        note=("'Balance after' is the running quantity ERPNext stored at that moment. "
              "A reconciliation posts a zero movement while changing the balance."),
    )


@ai_tool(
    name="sales_pipeline",
    description=(
        "Demand that has not been invoiced yet: open quotations and sales orders, with "
        "value, age and status. Use for 'what is in the pipeline', 'what have we quoted', "
        "'what is still open', 'how much work is waiting'. For what was already billed "
        "use the sales tools."
    ),
    params={
        "company": Param.text("Company.", optional=True),
        "limite": Param.integer("Maximum documents listed. Default 25.", optional=True),
    },
    doctypes=["Quotation", "Sales Order"],
    group="vendas",
)
def sales_pipeline(company=None, limite=25):
    company = resolve_company(company)
    today = nowdate()

    rows, by_stage = [], {}
    for doctype, label, party_field, open_states in (
        ("Quotation", "Quotation", "party_name", ["Open"]),
        ("Sales Order", "Order", "customer_name",
         ["To Deliver and Bill", "To Bill", "To Deliver"]),
    ):
        found = fetch(doctype,
                      fields=["name", party_field + " as party", "transaction_date",
                              "base_grand_total as value", "status"],
                      filters=submitted({"company": company,
                                         "status": ["in", open_states]}),
                      order_by="base_grand_total desc", limit=200)
        for r in found:
            stage = "%s · %s" % (label, r["status"])
            by_stage.setdefault(stage, {"count": 0, "value": 0.0})
            by_stage[stage]["count"] += 1
            by_stage[stage]["value"] += flt(r["value"])
            rows.append({
                "kind": label,
                "name": r["name"],
                "party": (r.get("party") or "").strip(),
                "status": r["status"],
                "date": r.get("transaction_date"),
                "value": flt(r["value"]),
            })

    rows.sort(key=lambda r: -r["value"])
    total = sum(r["value"] for r in rows)

    header = {"Open documents": len(rows), "Total open value": round(total, 2),
              "As at": today}
    for stage in sorted(by_stage):
        header[stage] = "%d · %s" % (by_stage[stage]["count"],
                                     round(by_stage[stage]["value"], 2))

    return ToolResult(
        columns=[text("kind", "Type"), text("name", "Document"), text("party", "Customer"),
                 text("status", "Status"), text("date", "Dated"),
                 currency("value", "Value")],
        rows=rows[: max(1, int(limite or 25))],
        source=describe("Quotation and Sales Order (submitted, open)", company),
        header=header,
        note=("Expired and lost quotations are excluded. Listing the largest first; "
              "the header totals cover every open document, not just those shown."),
    )
