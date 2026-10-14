"""Purchasing tools."""

from isoft_business_ai.ai.formatting import currency, integer, text
from isoft_business_ai.ai.query import date_range, describe, fetch, grand_total, submitted, total_note
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
    _note = total_note(_total, _n, _g, "purchase invoices", "suppliers")

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
