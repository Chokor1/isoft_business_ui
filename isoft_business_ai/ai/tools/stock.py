"""Stock tools.

``Bin`` has no company field, so the company scope is applied by resolving the
company's warehouses first and filtering on those. Explicit and cheap, and it
avoids relying on implicit link traversal in the query builder.
"""

from frappe.utils import add_days, date_diff, flt, nowdate

from isoft_business_ai.ai.formatting import currency, number, text
from isoft_business_ai.ai.query import MAX_REFERENCE_ROWS, describe, fetch, fetch_reference
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


def _company_warehouses(company):
    # Reference data: a site with more than 500 warehouses would otherwise be
    # scoped to an arbitrary subset of them.
    rows = fetch_reference(
        "Warehouse",
        fields=["name"],
        filters={"company": company, "is_group": 0},
    )
    return [r["name"] for r in rows]


@ai_tool(
    name="stock_actual",
    description=(
        "Quantity and value in stock per item and warehouse, right now. Returns a PARTIAL "
        "list of the highest-value lines. Use for 'stock of item X', 'what is in the "
        "warehouse', 'stock do artigo', 'o que temos em armazem'. For a total, use "
        "stock_valor_total instead. Set apenas_negativo for the negative-stock exception "
        "report - 'do I have negative stock', 'stock negativo' - which the value-ranked "
        "page cannot answer, because a negative line is never among the highest-value ones."
    ),
    params={
        "item_code": Param.text("Exact item code. Use procurar_artigo first if you only know the name.", optional=True),
        "warehouse": Param.text("Restrict to one warehouse.", optional=True),
        "item_group": Param.text("Restrict to one item group.", optional=True),
        "apenas_com_stock": Param.boolean("If true (the default), hide items with zero quantity.", optional=True),
        "apenas_negativo": Param.boolean(
            "If true, return ONLY lines whose quantity on hand is below zero, worst first, "
            "with a complete count. Use this for any negative-stock question.", optional=True),
        "limite": Param.integer("Maximum rows. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Bin", "Warehouse"],
    group="stock",
)
def stock_actual(item_code=None, warehouse=None, item_group=None, apenas_com_stock=True,
                 apenas_negativo=False, limite=50, company=None):
    company = resolve_company(company)

    if warehouse:
        warehouses = [warehouse]
    else:
        warehouses = _company_warehouses(company)

    if not warehouses:
        return ToolResult(
            columns=[text("item_code", "Item")],
            rows=[],
            source=describe("Bin", company),
            note="Company %s has no warehouses configured." % company,
        )

    filters = {"warehouse": ["in", warehouses]}
    if item_code:
        filters["item_code"] = item_code
    if apenas_negativo:
        filters["actual_qty"] = ["<", 0]
    elif apenas_com_stock:
        filters["actual_qty"] = ["!=", 0]
    if item_group:
        filters["`tabItem`.item_group"] = item_group

    extra = ["Item"] if item_group else []
    rows = fetch(
        "Bin",
        fields=["item_code", "warehouse", "actual_qty", "reserved_qty",
                "projected_qty", "valuation_rate", "stock_value"],
        filters=filters,
        # Ranking by value would bury the negatives: a short line is worth
        # little and would never reach a page of the highest-value rows.
        order_by="actual_qty asc" if apenas_negativo else "stock_value desc",
        limit=limite or 50,
        extra_doctypes=extra,
    )

    note = None
    if apenas_negativo:
        found = fetch("Bin", fields=["count(name) as n", "sum(actual_qty) as qty"],
                      filters=filters, extra_doctypes=extra)
        found = found[0] if found else {}
        n = int(found.get("n") or 0)
        note = ("Negative-stock exception report over every warehouse in this company. "
                "%d item/warehouse lines are below zero, %s units short in total%s."
                % (n, round(flt(found.get("qty")), 4),
                   "" if n <= len(rows) else "; the %d worst are listed" % len(rows))
                ) if n else ("No item/warehouse line in this company is below zero. "
                             "This is a complete check, not a capped page.")
    elif len(rows) >= (limite or 50):
        note = ("Partial list: only the %d highest-value rows are shown. "
                "For the total inventory value use the stock_valor_total tool; "
                "do not add up these rows." % len(rows))

    return ToolResult(
        columns=[
            text("item_code", "Item"),
            text("warehouse", "Warehouse"),
            number("actual_qty", "Qty on hand"),
            number("reserved_qty", "Qty reserved"),
            number("projected_qty", "Qty projected"),
            currency("valuation_rate", "Unit cost"),
            currency("stock_value", "Stock value"),
        ],
        rows=rows,
        source=describe("Bin (current stock)", company,
                        extra={"item": item_code, "warehouse": warehouse,
                               "group": item_group}),
        filters_applied=filters,
        note=note,
    )


@ai_tool(
    name="stock_valor_total",
    description=(
        "Total inventory value and number of items in stock, aggregated over ALL items with "
        "no row limit, optionally broken down per warehouse. Always use this when the "
        "question asks for a stock total, and never sum the rows of stock_actual, which is "
        "a partial list. 'total stock value', 'what is the stock worth in each warehouse', "
        "'valor total do inventario', 'valor por armazem'."
    ),
    params={
        "warehouse": Param.text("Restrict to one warehouse.", optional=True),
        "por_armazem": Param.boolean(
            "If true, one row per warehouse instead of a single total.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Bin", "Warehouse"],
    group="stock",
)
def stock_valor_total(warehouse=None, por_armazem=False, company=None):
    company = resolve_company(company)
    warehouses = [warehouse] if warehouse else _company_warehouses(company)

    if not warehouses:
        return ToolResult(
            columns=[currency("valor_total", "Total stock value")],
            rows=[],
            source=describe("Bin", company),
            note="Company %s has no warehouses configured." % company,
        )

    filters = {"warehouse": ["in", warehouses], "actual_qty": ["!=", 0]}
    fields = ["sum(stock_value) as valor_total", "sum(actual_qty) as quantidade_total",
              "count(name) as referencias"]

    if por_armazem:
        # Reference-shaped: the warehouse list is configuration, so it must not
        # be cut by the display cap or the breakdown would not add up.
        rows = fetch_reference(
            "Bin", fields=["warehouse"] + fields, filters=filters,
            group_by="warehouse", order_by="valor_total desc")
        total = round(sum(flt(r["valor_total"]) for r in rows), 2)
        rows.append({"warehouse": "TOTAL", "_style": "total", "valor_total": total,
                     "quantidade_total": round(sum(flt(r["quantidade_total"]) for r in rows), 2),
                     "referencias": sum(int(r["referencias"] or 0) for r in rows)})
        columns = [text("warehouse", "Warehouse"),
                   currency("valor_total", "Stock value"),
                   number("quantidade_total", "Quantity"),
                   number("referencias", "Items")]
        note = ("%d warehouse(s) hold stock, %s in total. The TOTAL row is the sum over "
                "every warehouse." % (len(rows) - 1, total))
    else:
        rows = fetch("Bin", fields=fields + ["count(distinct warehouse) as armazens"],
                     filters=filters)
        columns = [currency("valor_total", "Total stock value"),
                   number("quantidade_total", "Total quantity"),
                   number("referencias", "Items in stock"),
                   number("armazens", "Warehouses holding stock")]
        # The count that matters is how many warehouses hold anything, not how
        # many exist. Reporting the configured count said "Warehouses included:
        # 14" for a company whose entire stock sits in one of them - and the
        # assistant's own next answer said so, contradicting itself.
        holding = int(flt(rows[0].get("armazens"))) if rows else 0
        note = ("Aggregated over every item. %d of the company's %d warehouse(s) hold "
                "stock. Ask with por_armazem for the split per warehouse."
                % (holding, len(warehouses)))

    return ToolResult(
        columns=columns,
        rows=rows,
        source=describe("Bin (aggregated over all items)", company,
                        extra={"warehouse": warehouse,
                               "warehouses searched": len(warehouses)}),
        filters_applied={"company": company, "warehouse": warehouse,
                         "por_armazem": bool(por_armazem)},
        note=note,
    )


# --------------------------------------------------------------- stock risk

# What counts as slow: no outward movement at all in the window.
# What counts as thin: less than this many days of cover at the recent rate.
COVER_THIN_DAYS = 30
COVER_EXCESS_DAYS = 180


@ai_tool(
    name="stock_risco",
    description=(
        "Inventory risk per item: what is overstocked, what is slow-moving or dead, and "
        "what is close to running out. Compares quantity on hand against actual outward "
        "movement over a window to give days of cover. Use for 'slow moving stock', "
        "'what is overstocked', 'what will run out', 'dead stock', 'stock parado', "
        "'artigos sem movimento', 'o que vai acabar'."
    ),
    params={
        "dias": Param.integer(
            "Window of movement history to judge by, in days. Default 180.", optional=True),
        "risco": Param.enum(
            "Which risk to list. 'sem_movimento' = no outward movement in the window; "
            "'cobertura_baixa' = less than 30 days of cover; 'excesso' = more than 180 "
            "days of cover; 'todos' = everything with stock.",
            ["sem_movimento", "cobertura_baixa", "excesso", "todos"], optional=True),
        "item_group": Param.text("Restrict to one item group.", optional=True),
        "warehouse": Param.text(
            "Restrict to one warehouse or shop. Exact warehouse name.", optional=True),
        "limite": Param.integer("Maximum rows. Default 30.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Bin", "Warehouse", "Stock Ledger Entry"],
    group="stock",
)
def stock_risco(dias=180, risco="todos", item_group=None, warehouse=None, limite=30,
                company=None):
    company = resolve_company(company)
    dias = max(7, min(int(dias or 180), 730))
    limite = max(1, min(int(limite or 30), 200))
    since = add_days(nowdate(), -dias)

    if warehouse:
        known = _company_warehouses(company)
        if warehouse not in known:
            return ToolResult(
                columns=[text("item_code", "Item")], rows=[],
                source=describe("Bin", company),
                note=("There is no warehouse named '%s' in %s. This is not an empty "
                      "result, it is a wrong parameter: call procurar_armazem to get "
                      "the exact name, then try again." % (warehouse, company)))
        warehouses = [warehouse]
    else:
        warehouses = _company_warehouses(company)
    if not warehouses:
        return ToolResult(columns=[text("item_code", "Item")], rows=[],
                          source=describe("Bin", company),
                          note="Company %s has no warehouses configured." % company)

    # On hand and value, per item, across the company's warehouses. Reference
    # data: the item master sets the row count, so it must not be capped at the
    # display limit or the verdicts would cover an arbitrary subset.
    bin_filters = {"warehouse": ["in", warehouses], "actual_qty": [">", 0]}
    extra = []
    if item_group:
        bin_filters["`tabItem`.item_group"] = item_group
        extra = ["Item"]
    on_hand = fetch_reference(
        "Bin",
        fields=["item_code", "sum(actual_qty) as qty", "sum(stock_value) as valor"],
        filters=bin_filters,
        group_by="item_code",
        order_by="valor desc",
    ) if not extra else fetch(
        "Bin",
        fields=["item_code", "sum(actual_qty) as qty", "sum(stock_value) as valor"],
        filters=bin_filters, group_by="item_code", order_by="valor desc",
        limit=MAX_REFERENCE_ROWS, extra_doctypes=extra,
    )
    if not on_hand:
        return ToolResult(columns=[text("item_code", "Item")], rows=[],
                          source=describe("Bin", company),
                          note="No item has stock in %s." % company)

    # Outward movement over the window. Consumption is what actually left the
    # building, so only negative actual_qty counts, and cancelled entries do not.
    out = fetch_reference(
        "Stock Ledger Entry",
        fields=["item_code", "sum(actual_qty) as movimento",
                "max(posting_date) as ultima_saida"],
        filters={"warehouse": ["in", warehouses], "is_cancelled": 0,
                 "posting_date": [">=", since], "actual_qty": ["<", 0]},
        group_by="item_code",
    )
    moved = {r["item_code"]: r for r in out}

    # When an item has not moved inside the window the question is usually
    # "how long has it sat there", so the last movement of ANY kind, ever, is
    # what answers it - not a null because the window saw nothing.
    ever = {}
    for r in fetch_reference(
            "Stock Ledger Entry",
            fields=["item_code", "max(posting_date) as ultima_saida"],
            filters={"warehouse": ["in", warehouses], "is_cancelled": 0,
                     "actual_qty": ["<", 0]},
            group_by="item_code"):
        ever[r["item_code"]] = r["ultima_saida"]
    arrived = {}
    for r in fetch_reference(
            "Stock Ledger Entry",
            fields=["item_code", "max(posting_date) as ultima_entrada"],
            filters={"warehouse": ["in", warehouses], "is_cancelled": 0,
                     "actual_qty": [">", 0]},
            group_by="item_code"):
        arrived[r["item_code"]] = r["ultima_entrada"]

    # Reorder levels are optional on this kind of site, so they refine the
    # verdict where they exist and are never required for one.
    reorder = {}
    try:
        for r in fetch_reference(
                "Item Reorder",
                fields=["parent", "sum(warehouse_reorder_level) as nivel"],
                filters={"warehouse": ["in", warehouses]}, group_by="parent"):
            reorder[r["parent"]] = flt(r["nivel"])
    except Exception:
        reorder = {}

    rows = []
    for b in on_hand:
        code = b["item_code"]
        qty = flt(b["qty"])
        m = moved.get(code)
        saida = abs(flt(m["movimento"])) if m else 0.0
        por_dia = saida / float(dias) if saida else 0.0
        cobertura = (qty / por_dia) if por_dia > 0 else None
        nivel = reorder.get(code)

        # The movement verdict is primary and the buckets are disjoint, so the
        # tally adds up and "slow moving" means every slow-moving item. A
        # reorder breach is an extra flag on top; letting it overwrite the
        # verdict quietly dropped an item out of 'sem movimento' and made the
        # slow-moving total understate itself by exactly that item.
        if saida <= 0:
            verdict = "sem movimento"
        elif cobertura is not None and cobertura < COVER_THIN_DAYS:
            verdict = "cobertura baixa"
        elif cobertura is not None and cobertura > COVER_EXCESS_DAYS:
            verdict = "excesso"
        else:
            verdict = "normal"
        abaixo = bool(nivel and qty <= nivel)

        rows.append({
            "item_code": code,
            "qty": round(qty, 2),
            "valor": round(flt(b["valor"]), 2),
            "saida_periodo": round(saida, 2),
            "cobertura_dias": (round(cobertura) if cobertura is not None else None),
            "ultima_saida": (m or {}).get("ultima_saida") or ever.get(code),
            "ultima_entrada": arrived.get(code),
            "dias_parado": (date_diff(nowdate(), ever[code]) if ever.get(code)
                            else (date_diff(nowdate(), arrived[code])
                                  if arrived.get(code) else None)),
            "nivel_reposicao": nivel,
            "abaixo_reposicao": "yes" if abaixo else "",
            "risco": verdict,
        })

    if risco == "sem_movimento":
        selected = [r for r in rows if r["risco"] == "sem movimento"]
    elif risco == "cobertura_baixa":
        # Thin cover or already under the reorder level: both mean "may run out".
        selected = [r for r in rows
                    if r["risco"] == "cobertura baixa" or r["abaixo_reposicao"]]
    elif risco == "excesso":
        selected = [r for r in rows if r["risco"] == "excesso"]
    else:
        selected = list(rows)

    # Value first: a dead item worth nothing is not the one to act on.
    selected.sort(key=lambda r: -r["valor"])
    listed = selected[:limite]

    tally = {}
    for r in rows:
        tally[r["risco"]] = tally.get(r["risco"], 0) + 1
    under = sum(1 for r in rows if r["abaixo_reposicao"])
    valor_risco = round(sum(r["valor"] for r in selected), 2)

    note = (
        "%d items hold stock. By movement over the last %d days: %s. "
        "The %d selected hold %s in value; the table lists the %d largest. "
        "%s"
        % (len(rows), dias,
           ", ".join("%d %s" % (n, k) for k, n in sorted(tally.items(), key=lambda x: -x[1])),
           len(selected), valor_risco, len(listed),
           ("%d item(s) are at or below a configured reorder level." % under) if under
           else "Reorder levels are set on almost no item here, so 'may run out' is "
                "judged from recent consumption rather than from a configured level.")
    )

    return ToolResult(
        columns=[
            text("item_code", "Item"),
            number("qty", "On hand"),
            currency("valor", "Stock value"),
            number("saida_periodo", "Issued in period"),
            number("cobertura_dias", "Days of cover"),
            text("ultima_saida", "Last issued"),
            text("ultima_entrada", "Last received"),
            number("dias_parado", "Days since it moved out"),
            number("nivel_reposicao", "Reorder level"),
            text("abaixo_reposicao", "Below reorder"),
            text("risco", "Risk"),
        ],
        rows=listed,
        source=describe("Bin + Stock Ledger Entry", company,
                        extra={"window": "%s to %s" % (since, nowdate()), "risk": risco,
                               "warehouse": warehouse or "all in company"}),
        filters_applied={"company": company, "dias": dias, "risco": risco,
                         "item_group": item_group, "warehouse": warehouse},
        note=note,
    )


@ai_tool(
    name="stock_movimentos",
    description=(
        "What moved stock over a period, grouped by the kind of document that moved it, "
        "and the largest individual documents. This is how you answer 'why did stock go "
        "up', 'what caused the stock increase', 'where did the stock come from', 'porque "
        "subiu o stock'. Purchases are only one of the ways stock arrives: receipts, "
        "manufacturing entries and reconciliations all move it too, and on this kind of "
        "site a single stock entry can be larger than a year of purchasing. Never "
        "attribute a stock movement to purchase invoices without checking here first."
    ),
    params={
        "from_date": Param.date("Start of the period."),
        "to_date": Param.date("End of the period."),
        "item_code": Param.text("Restrict to one item.", optional=True),
        "warehouse": Param.text("Restrict to one warehouse.", optional=True),
        "limite": Param.integer("Largest documents to list. Default 15.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Stock Ledger Entry", "Warehouse"],
    group="stock",
)
def stock_movimentos(from_date, to_date, item_code=None, warehouse=None, limite=15,
                     company=None):
    company = resolve_company(company)
    limite = max(1, min(int(limite or 15), 100))

    if warehouse:
        known = _company_warehouses(company)
        if warehouse not in known:
            return ToolResult(
                columns=[text("voucher_type", "Document type")], rows=[],
                source=describe("Stock Ledger Entry", company),
                note=("There is no warehouse named '%s' in %s. Call procurar_armazem for "
                      "the exact name." % (warehouse, company)))
        warehouses = [warehouse]
    else:
        warehouses = _company_warehouses(company)
    if not warehouses:
        return ToolResult(columns=[text("voucher_type", "Document type")], rows=[],
                          source=describe("Stock Ledger Entry", company),
                          note="Company %s has no warehouses configured." % company)

    filters = {"warehouse": ["in", warehouses], "is_cancelled": 0,
               "posting_date": ["between", [from_date, to_date]]}
    if item_code:
        filters["item_code"] = item_code

    # By document type first: the shape of the answer is usually here.
    by_type = fetch_reference(
        "Stock Ledger Entry",
        fields=["voucher_type", "count(name) as lancamentos",
                "sum(actual_qty) as quantidade",
                "sum(stock_value_difference) as valor"],
        filters=filters, group_by="voucher_type", order_by="valor desc",
    )
    # Then the individual documents that moved the most value.
    by_doc = fetch(
        "Stock Ledger Entry",
        fields=["voucher_type", "voucher_no", "sum(actual_qty) as quantidade",
                "sum(stock_value_difference) as valor", "max(posting_date) as data"],
        filters=filters, group_by="voucher_no", order_by="valor desc", limit=limite,
    )

    rows = []
    for r in by_type:
        rows.append({"voucher_type": r["voucher_type"], "voucher_no": "(all)",
                     "data": "", "quantidade": round(flt(r["quantidade"]), 2),
                     "valor": round(flt(r["valor"]), 2),
                     "lancamentos": r["lancamentos"]})
    for r in by_doc:
        rows.append({"voucher_type": r["voucher_type"], "voucher_no": r["voucher_no"],
                     "data": r["data"], "quantidade": round(flt(r["quantidade"]), 2),
                     "valor": round(flt(r["valor"]), 2), "lancamentos": None})

    net = round(sum(flt(r["valor"]) for r in by_type), 2)
    entrada = round(sum(flt(r["valor"]) for r in by_type if flt(r["valor"]) > 0), 2)
    saida = round(sum(flt(r["valor"]) for r in by_type if flt(r["valor"]) < 0), 2)

    return ToolResult(
        columns=[
            text("voucher_type", "Document type"),
            text("voucher_no", "Document"),
            text("data", "Date"),
            number("quantidade", "Qty moved"),
            currency("valor", "Stock value moved"),
            number("lancamentos", "Entries"),
        ],
        rows=rows,
        source=describe("Stock Ledger Entry (not cancelled)", company, from_date, to_date,
                        extra={"warehouse": warehouse or "all in company",
                               "item": item_code}),
        filters_applied={"company": company, "from_date": from_date, "to_date": to_date,
                         "item_code": item_code, "warehouse": warehouse},
        note=("Net stock value movement over the period: %s (in %s, out %s). Rows marked "
              "'(all)' are the per-document-type totals over everything; the rows below "
              "them are the %d individual documents that moved the most value. Use these "
              "to explain a stock change - do not infer it from purchase invoices."
              % (net, entrada, saida, len(by_doc))),
    )
