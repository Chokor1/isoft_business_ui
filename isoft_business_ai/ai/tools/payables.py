"""Payables: what the company owes suppliers."""

from frappe.utils import nowdate

from isoft_business_ai.ai.aging import BUCKETS, build_aging
from isoft_business_ai.ai.formatting import currency, date, integer, text
from isoft_business_ai.ai.query import describe, fetch, grand_total, submitted
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="contas_a_pagar",
    description=(
        "Supplier outstanding balances with aging buckets, plus the correct grand total. "
        "Use for 'how much do we owe', 'accounts payable', 'unpaid supplier invoices', "
        "'quanto devemos', 'contas a pagar'."
    ),
    params={
        "as_on": Param.date("Reference date. Omit for today.", optional=True),
        "supplier": Param.text("Restrict to one supplier (exact code).", optional=True),
        "apenas_vencido": Param.boolean("If true, show only what is already overdue.", optional=True),
        "ascendente": Param.boolean(
            "If true, list the SMALLEST balances first. The default is largest first, and "
            "the bottom of that page is not the smallest of the whole set.", optional=True),
        "limite": Param.integer("Maximum suppliers listed. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Purchase Invoice"],
    group="tesouraria",
)
def contas_a_pagar(as_on=None, supplier=None, apenas_vencido=False, limite=50, ascendente=False, company=None):
    company = resolve_company(company)
    as_on = as_on or nowdate()

    rows, grand = build_aging(
        "Purchase Invoice", "supplier", "supplier_name", company, as_on,
        party=supplier, apenas_vencido=apenas_vencido, limite=limite,
        ascendente=bool(ascendente),
    )

    columns = [text("party", "Supplier"), text("party_name", "Name")]
    columns += [currency(k, label) for k, label in BUCKETS]
    columns += [currency("total", "Total outstanding"), integer("facturas", "Invoices")]

    note = (
        "Grand total across all %d suppliers with a balance: %s (%d invoices). "
        "The table lists the %d largest."
        % (grand["parties"], round(grand["total"], 2), grand["facturas"], grand["listed"])
    )

    return ToolResult(
        columns=columns,
        rows=rows,
        source=describe("Purchase Invoice open (submitted, outstanding > 0)", company,
                        extra={"aging at": as_on, "supplier": supplier,
                               "filter": "overdue only" if apenas_vencido else "all open"}),
        filters_applied={"company": company, "as_on": as_on, "supplier": supplier,
                         "apenas_vencido": apenas_vencido},
        note=note,
    )


@ai_tool(
    name="facturas_de_compra",
    description=(
        "Open supplier invoices with their due dates and outstanding amounts, soonest "
        "due first. This is what answers 'when is that due', 'what do we have to pay and "
        "when', 'upcoming supplier payments', 'quando vence', 'o que temos a pagar'. "
        "contas_a_pagar gives the aging summary; this gives the documents behind it."
    ),
    params={
        "supplier": Param.text("Restrict to one supplier (exact code).", optional=True),
        "ate": Param.date("Only invoices due on or before this date.", optional=True),
        "apenas_em_aberto": Param.boolean(
            "If true (the default), only invoices still carrying a balance.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'vencimento' is soonest due first (the default). 'valor' is "
            "largest outstanding first - use it for 'the biggest bills we owe'. "
            "'valor_asc' is SMALLEST outstanding first. 'total' is largest invoice value "
            "first. The tail of a largest-first page is not the smallest of the set.",
            ["vencimento", "valor", "valor_asc", "total"], optional=True),
        "limite": Param.integer("Maximum rows. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Purchase Invoice"],
    group="tesouraria",
)
def facturas_de_compra(supplier=None, ate=None, apenas_em_aberto=True,
                       ordenar_por="vencimento", limite=50, company=None):
    company = resolve_company(company)
    limite = max(1, min(int(limite or 50), 200))

    filters = submitted({"company": company})
    if apenas_em_aberto:
        filters["outstanding_amount"] = [">", 0]
    if supplier:
        filters["supplier"] = supplier
    if ate:
        filters["due_date"] = ["<=", ate]

    rows = fetch(
        "Purchase Invoice",
        fields=["name", "supplier", "supplier_name", "posting_date", "due_date",
                "base_grand_total", "outstanding_amount", "status"],
        filters=filters,
        # Soonest due first by default: the question is usually what to pay next.
        order_by={"valor": "outstanding_amount desc",
                  "valor_asc": "outstanding_amount asc",
                  "total": "base_grand_total desc"}.get(ordenar_por or "vencimento",
                                                        "due_date asc"),
        limit=limite,
    )
    _total, _n, _g = grand_total("Purchase Invoice", filters, "outstanding_amount",
                                 group_field="supplier")
    overdue, _dn, _dg = grand_total(
        "Purchase Invoice", dict(filters, due_date=["<", nowdate()]),
        "outstanding_amount")

    return ToolResult(
        columns=[
            text("name", "Invoice"),
            text("supplier_name", "Supplier"),
            date("posting_date", "Posted"),
            date("due_date", "Due"),
            currency("base_grand_total", "Total"),
            currency("outstanding_amount", "Outstanding"),
            text("status", "Status"),
        ],
        rows=rows,
        source=describe("Purchase Invoice (submitted, open)", company,
                        extra={"supplier": supplier, "due on or before": ate}),
        filters_applied={"company": company, "supplier": supplier, "ate": ate,
                         "ordenar_por": ordenar_por},
        links=[{"doctype": "Purchase Invoice", "name": r["name"],
                "label": "%s  %s" % (r["name"], r.get("supplier_name") or "")}
               for r in rows[:10]],
        note=("Outstanding over everything these filters match: %s across %d suppliers in "
              "%d invoices, of which %s is already past its due date as at %s. The table "
              "is a capped page - do not add its rows up yourself. Sorted by %s."
              % (round(_total, 2), _g, _n, round(overdue, 2), nowdate(),
                 {"valor": "outstanding balance, largest first",
                  "valor_asc": "outstanding balance, smallest first",
                  "total": "invoice value, largest first"}.get(
                      ordenar_por or "vencimento", "due date, soonest first"))),
    )
