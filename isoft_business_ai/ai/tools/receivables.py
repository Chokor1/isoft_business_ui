"""Receivables: what customers owe, and how overdue it is."""

from frappe.utils import flt, nowdate

from isoft_business_ai.ai.aging import BUCKETS, aging_note, build_aging
from isoft_business_ai.ai.formatting import currency, integer, text
from isoft_business_ai.ai.query import describe, fetch
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="contas_a_receber",
    description=(
        "Customer outstanding balances with aging buckets: not due, 1-30, 31-60, 61-90 and "
        "over 90 days. Also returns the correct grand total even when the customer list is "
        "truncated. Use for 'who owes us money', 'overdue debt', 'accounts receivable', "
        "'quem me deve dinheiro', 'divida vencida', 'contas a receber'."
    ),
    params={
        "as_on": Param.date("Aging reference date. Omit for today.", optional=True),
        "customer": Param.text("Restrict to one customer (exact code).", optional=True),
        "apenas_vencido": Param.boolean("If true, show only what is already overdue.", optional=True),
        "ascendente": Param.boolean(
            "If true, list the SMALLEST balances first. The default is largest first, and "
            "the bottom of that page is not the smallest of the whole set.", optional=True),
        "limite": Param.integer("Maximum customers listed. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="tesouraria",
)
def contas_a_receber(as_on=None, customer=None, apenas_vencido=False, limite=50, ascendente=False, company=None):
    company = resolve_company(company)
    as_on = as_on or nowdate()

    rows, grand = build_aging(
        "Sales Invoice", "customer", "customer_name", company, as_on,
        party=customer, apenas_vencido=apenas_vencido, limite=limite,
        ascendente=bool(ascendente),
    )

    columns = [text("party", "Customer"), text("party_name", "Name")]
    columns += [currency(k, label) for k, label in BUCKETS]
    columns += [currency("total", "Total outstanding"), integer("facturas", "Invoices")]

    note = aging_note(grand, "customers", apenas_vencido=bool(apenas_vencido))

    return ToolResult(
        columns=columns,
        rows=rows,
        source=describe("Sales Invoice open (submitted, outstanding > 0)", company,
                        extra={"aging at": as_on, "customer": customer,
                               "filter": "overdue only" if apenas_vencido else "all open"}),
        filters_applied={"company": company, "as_on": as_on, "customer": customer,
                         "apenas_vencido": apenas_vencido},
        note=note,
    )


@ai_tool(
    name="extrato_cliente",
    description=(
        "Customer account statement: every accounting entry (invoices, receipts, credit "
        "notes) on the receivable account, with a running balance. Use for "
        "'customer statement', 'account ledger', 'extrato do cliente', 'conta corrente'."
    ),
    params={
        "customer": Param.text("Exact customer code. Use procurar_cliente first if you only know the name."),
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry"],
    group="tesouraria",
)
def extrato_cliente(customer, from_date, to_date, company=None):
    company = resolve_company(company)
    filters = {
        "company": company,
        "party_type": "Customer",
        "party": customer,
        "is_cancelled": 0,
        "posting_date": ["between", [from_date, to_date]],
    }
    rows = fetch(
        "GL Entry",
        fields=["posting_date", "voucher_type", "voucher_no", "account", "debit", "credit", "remarks"],
        filters=filters,
        order_by="posting_date asc, creation asc",
        limit=500,
    )

    saldo = 0.0
    for r in rows:
        saldo += flt(r.get("debit")) - flt(r.get("credit"))
        r["saldo"] = saldo

    return ToolResult(
        columns=[
            text("posting_date", "Date"),
            text("voucher_type", "Type"),
            text("voucher_no", "Document"),
            currency("debit", "Debit"),
            currency("credit", "Credit"),
            currency("saldo", "Running balance"),
        ],
        rows=rows,
        source=describe("GL Entry (party_type=Customer, not cancelled)", company, from_date, to_date,
                        {"customer": customer}),
        filters_applied=filters,
        note="Running balance computed over the returned rows, starting from zero at %s." % from_date,
    )
