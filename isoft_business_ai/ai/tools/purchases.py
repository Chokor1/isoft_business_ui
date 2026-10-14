"""Purchasing tools."""

from isoft_business_ai.ai.formatting import currency, integer, number, text
from isoft_business_ai.ai.query import (date_range, describe, fetch, grand_total,
                                        grouped_total, page_share, submitted, total_note)
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="compras_total",
    description=(
        "Total purchases invoiced by suppliers in a period, with an optional ranking per "
        "supplier. Use for 'how much did we buy', 'main suppliers', 'quanto compramos', "
        "'principais fornecedores'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "por_fornecedor": Param.boolean(
            "If true, return the per-supplier breakdown; if false, only the total. Default true.",
            optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'valor' is most spent first (the default); 'valor_asc' is least "
            "spent first. The tail of a largest-first page is not the smallest of the set.",
            ["valor", "valor_asc"], optional=True),
        "limite": Param.integer("Maximum suppliers. Default 20.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Purchase Invoice"],
    group="compras",
)
def compras_total(from_date, to_date, por_fornecedor=True, ordenar_por="valor",
                  limite=20, company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))

    if not por_fornecedor:
        rows = fetch(
            "Purchase Invoice",
            fields=["sum(base_grand_total) as total", "count(name) as facturas"],
            filters=filters,
        )
        return ToolResult(
            columns=[currency("total", "Total purchased"), integer("facturas", "Invoices")],
            rows=rows,
            source=describe("Purchase Invoice (submitted)", company, from_date, to_date),
            filters_applied=filters,
        )

    rows = fetch(
        "Purchase Invoice",
        fields=["supplier", "supplier_name", "sum(base_grand_total) as total",
                "count(name) as facturas"],
        filters=filters,
        group_by="supplier",
        order_by="total asc" if ordenar_por == "valor_asc" else "total desc",
        limit=limite or 20,
    )
    # The listed rows are a capped page; this total is not.
    _total, _n, _g = grand_total("Purchase Invoice", filters, "base_grand_total",
                                 group_field="supplier")
    _note = total_note(_total, _n, _g, "purchase invoices", "suppliers",
                       rows=rows, value_key="total")

    return ToolResult(
        columns=[
            text("supplier", "Supplier"),
            text("supplier_name", "Name"),
            currency("total", "Total purchased"),
            integer("facturas", "Invoices"),
        ],
        rows=rows,
        source=describe("Purchase Invoice (submitted)", company, from_date, to_date),
        filters_applied=filters,
        note=_note,
    )


@ai_tool(
    name="compras_por_artigo",
    description=(
        "Ranking of items/products by value or quantity purchased in a period, optionally "
        "from ONE supplier. The supplier filter is the only way to break a supplier's "
        "deliveries down to item level - use it for 'what do we buy from X', 'what did this "
        "supplier invoice us for', 'o que compramos a este fornecedor'. Also use for 'what "
        "do we buy most', 'artigos mais comprados'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "limite": Param.integer("How many items to return. Default 20.", optional=True),
        "item_group": Param.text("Filter by item group.", optional=True),
        "supplier": Param.text(
            "Restrict to ONE supplier (exact supplier code). Call procurar_fornecedor "
            "first if you only know the name.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'valor' and 'quantidade' are largest first (most bought); "
            "'valor_asc' and 'quantidade_asc' are smallest first - use those for 'what we "
            "barely buy'. Never read the bottom of a descending page as the smallest.",
            ["valor", "quantidade", "valor_asc", "quantidade_asc"], optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Purchase Invoice", "Purchase Invoice Item"],
    group="compras",
)
def compras_por_artigo(from_date, to_date, limite=20, item_group=None, supplier=None,
                       ordenar_por="valor", company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    if item_group:
        filters["`tabPurchase Invoice Item`.item_group"] = item_group
    if supplier:
        filters["supplier"] = supplier

    order = {
        "valor": "valor desc",
        "quantidade": "quantidade desc",
        "valor_asc": "valor asc",
        "quantidade_asc": "quantidade asc",
    }.get(ordenar_por or "valor", "valor desc")
    rows = fetch(
        "Purchase Invoice",
        fields=[
            "`tabPurchase Invoice Item`.item_code as item_code",
            "`tabPurchase Invoice Item`.item_name as item_name",
            "sum(`tabPurchase Invoice Item`.base_net_amount) as valor",
            "sum(`tabPurchase Invoice Item`.stock_qty) as quantidade",
        ],
        filters=filters,
        group_by="`tabPurchase Invoice Item`.item_code",
        order_by=order,
        limit=limite or 20,
        extra_doctypes=["Purchase Invoice Item"],
    )
    # The listed rows are a capped page; this total is not. As on the sales
    # side the figure lives on the child table, so the total comes from reading
    # every item uncapped rather than from the parent's own net total.
    _total, _g, _complete = grouped_total(
        "Purchase Invoice",
        fields=["`tabPurchase Invoice Item`.item_code as item_code",
                "sum(`tabPurchase Invoice Item`.base_net_amount) as valor"],
        filters=filters,
        group_by="`tabPurchase Invoice Item`.item_code",
        value_key="valor",
        extra_doctypes=["Purchase Invoice Item"])
    _note = ("Grand total over everything these filters match: %s net across %d items. "
             "The table is a capped page of that set - do not add its rows up yourself. %s"
             % (round(_total, 2), _g, page_share(rows, "valor", _total)))
    if not _complete:
        _note += (" More items matched than this total could read, so it is a floor, "
                  "not the full figure.")

    return ToolResult(
        columns=[
            text("item_code", "Code"),
            text("item_name", "Item"),
            currency("valor", "Value purchased"),
            number("quantidade", "Quantity"),
        ],
        rows=rows,
        source=describe("Purchase Invoice Item (submitted invoices)", company,
                        from_date, to_date,
                        {"item group": item_group, "supplier": supplier,
                         "ordered by": ordenar_por}),
        filters_applied=filters,
        note=_note,
    )
