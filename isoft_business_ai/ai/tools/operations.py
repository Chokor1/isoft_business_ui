"""Stock movement and the buying and selling pipelines.

Both answer "how did we get here" rather than "where are we now": the existing
stock tools read the current balance, and the sales tools read what was already
invoiced. These read the movements and the demand that has not landed yet.
"""

from frappe.utils import add_days, date_diff, flt, nowdate

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
        note=("'Balance after' is the running quantity ISOFT ERP stored at that moment. "
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


@ai_tool(
    name="compras_pipeline",
    description=(
        "Purchase orders placed but not yet fully received or billed: value, age, how much "
        "has arrived and how much is still outstanding. Use for 'open purchase orders', "
        "'what have we ordered that has not arrived', 'committed spend', 'encomendas "
        "pendentes', and - with dias_minimos - 'orders sitting unreceived for more than N "
        "days'. The sales_pipeline tool is the selling side and does not cover this."
    ),
    params={
        "dias_minimos": Param.integer(
            "Only orders at least this many days old. Use 30 for 'sitting for more than "
            "30 days'. Default 0, meaning every open order.", optional=True),
        "supplier": Param.text("Restrict to one supplier (exact code).", optional=True),
        "company": Param.text("Company.", optional=True),
        "limite": Param.integer("Maximum orders listed. Default 25.", optional=True),
    },
    doctypes=["Purchase Order"],
    group="compras",
)
def compras_pipeline(dias_minimos=0, supplier=None, company=None, limite=25):
    company = resolve_company(company)
    today = nowdate()
    dias_minimos = int(dias_minimos or 0)

    filters = submitted({
        "company": company,
        "status": ["in", ["To Receive and Bill", "To Receive", "To Bill"]],
    })
    if supplier:
        filters["supplier"] = supplier
    if dias_minimos:
        filters["transaction_date"] = ["<=", add_days(today, -dias_minimos)]

    found = fetch("Purchase Order",
                  fields=["name", "supplier", "supplier_name", "transaction_date", "status",
                          "base_grand_total as value", "per_received", "per_billed"],
                  filters=filters, order_by="base_grand_total desc", limit=500)

    rows, by_stage = [], {}
    committed = pending = 0.0
    for r in found:
        value = flt(r["value"])
        # What has not arrived yet, pro rata on the order value: Purchase Order
        # carries a received percentage, not a received amount.
        outstanding = value * (100.0 - flt(r.get("per_received"))) / 100.0
        committed += value
        pending += outstanding
        by_stage.setdefault(r["status"], {"count": 0, "value": 0.0})
        by_stage[r["status"]]["count"] += 1
        by_stage[r["status"]]["value"] += value
        rows.append({
            "name": r["name"],
            "supplier": (r.get("supplier_name") or r.get("supplier") or "").strip(),
            "status": r["status"],
            "date": r.get("transaction_date"),
            "dias": date_diff(today, r.get("transaction_date")) if r.get("transaction_date") else None,
            "value": value,
            "recebido_pct": flt(r.get("per_received")),
            "a_receber": outstanding,
        })

    rows.sort(key=lambda r: -r["value"])
    header = {
        "Open orders": len(rows),
        "Committed value": round(committed, 2),
        "Still to be received": round(pending, 2),
        "As at": today,
    }
    if dias_minimos:
        header["Older than"] = "%d days" % dias_minimos
    for stage in sorted(by_stage):
        header[stage] = "%d · %s" % (by_stage[stage]["count"], round(by_stage[stage]["value"], 2))

    note = ("Submitted purchase orders still awaiting receipt or billing%s. The header "
            "totals cover every one of the %d open orders, not just the %d listed, so "
            "quote them rather than adding the rows up. 'Still to be received' is the "
            "order value weighted by the share not yet received."
            % (" and at least %d days old" % dias_minimos if dias_minimos else "",
               len(rows), min(len(rows), max(1, int(limite or 25)))))
    if not rows:
        note = ("No submitted purchase order is open%s. This is a complete check."
                % (" and at least %d days old" % dias_minimos if dias_minimos else ""))

    return ToolResult(
        columns=[text("name", "Order"), text("supplier", "Supplier"),
                 text("status", "Status"), text("date", "Dated"),
                 integer("dias", "Days old"), currency("value", "Order value"),
                 number("recebido_pct", "% received"), currency("a_receber", "Still to receive")],
        rows=rows[: max(1, int(limite or 25))],
        source=describe("Purchase Order (submitted, open)", company,
                        extra={"supplier": supplier,
                               "older than": "%d days" % dias_minimos if dias_minimos else None}),
        header=header,
        note=note,
    )


@ai_tool(
    name="por_facturar",
    description=(
        "Goods that have moved but have not been invoiced: delivery notes not yet "
        "billed to the customer, or purchase receipts not yet billed by the supplier. "
        "Use for 'what have we delivered but not invoiced', 'unbilled deliveries', "
        "'what has arrived that we have not been invoiced for', 'por facturar', "
        "'entregas nao facturadas', 'guias por facturar'. This is revenue not yet "
        "billed, or a cost not yet booked - no other tool sees it, because the "
        "invoice that would carry it does not exist yet."
    ),
    params={
        "direccao": Param.enum(
            "'vendas' for deliveries to customers not yet invoiced (the default), "
            "'compras' for receipts from suppliers not yet billed.",
            ["vendas", "compras"], optional=True),
        "from_date": Param.date("Start date. Optional - omit for everything open.",
                                optional=True),
        "to_date": Param.date("End date.", optional=True),
        "limite": Param.integer("Maximum documents listed. Default 25.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Delivery Note", "Purchase Receipt"],
    group="operacoes",
)
def por_facturar(direccao="vendas", from_date=None, to_date=None, limite=25, company=None):
    company = resolve_company(company)
    selling = (direccao or "vendas") == "vendas"
    doctype = "Delivery Note" if selling else "Purchase Receipt"
    party_field = "customer" if selling else "supplier"
    party_name = "customer_name" if selling else "supplier_name"

    filters = submitted({"company": company, "per_billed": ["<", 99.99]})
    if from_date and to_date:
        filters.update(date_range("posting_date", from_date, to_date))

    found = fetch(doctype,
                  fields=["name", party_field, party_name, "posting_date", "status",
                          "base_grand_total as value", "per_billed"],
                  filters=filters, order_by="posting_date asc", limit=500)

    today = nowdate()
    rows, total, pending = [], 0.0, 0.0
    for r in found:
        value = flt(r["value"])
        unbilled = value * (100.0 - flt(r.get("per_billed"))) / 100.0
        total += value
        pending += unbilled
        rows.append({
            "name": r["name"],
            "party": (r.get(party_name) or r.get(party_field) or "").strip(),
            "date": r.get("posting_date"),
            "dias": date_diff(today, r.get("posting_date")) if r.get("posting_date") else None,
            "status": r.get("status"),
            "value": value,
            "facturado_pct": flt(r.get("per_billed")),
            "por_facturar": unbilled,
        })
    rows.sort(key=lambda r: -r["por_facturar"])

    noun = "deliveries to customers" if selling else "receipts from suppliers"
    header = {
        "Open documents": len(rows),
        "Total document value": round(total, 2),
        "Still to be invoiced": round(pending, 2),
        "As at": today,
    }
    note = ("%d submitted %s are not fully invoiced, %s of their value still to be "
            "billed. The header totals cover every one of them, not just the %d "
            "listed, so quote them rather than adding the rows up. 'Still to be "
            "invoiced' is each document's value weighted by the share not yet billed."
            % (len(rows), noun, round(pending, 2), min(len(rows), max(1, int(limite or 25)))))
    if not rows:
        note = ("Every submitted %s is fully invoiced. This is a complete check, not a "
                "capped page." % noun[:-1])

    return ToolResult(
        columns=[text("name", "Document"),
                 text("party", "Customer" if selling else "Supplier"),
                 text("date", "Dated"), integer("dias", "Days old"),
                 text("status", "Status"), currency("value", "Document value"),
                 number("facturado_pct", "% invoiced"),
                 currency("por_facturar", "Still to invoice")],
        rows=rows[: max(1, int(limite or 25))],
        source=describe("%s (submitted, not fully invoiced)" % doctype, company,
                        from_date, to_date),
        filters_applied=filters,
        header=header,
        note=note,
    )
