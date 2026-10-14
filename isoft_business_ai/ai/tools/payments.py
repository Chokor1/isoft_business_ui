# -*- coding: utf-8 -*-
"""Money actually moved: receipts from customers and payments to suppliers.

Separate from receivables and payables on purpose. Those tools answer what is
owed; this one answers what was banked, which is the question an accounts
manager asks every week and the one the ledger tools kept failing: a general
ledger extract shows postings, not a collections figure.
"""

from frappe.utils import nowdate

from isoft_business_ai.ai.formatting import currency, date, integer, text
from isoft_business_ai.ai.query import (describe, fetch, grand_total, submitted,
                                        total_note)
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company

# Payment Entry stores the company-currency figure on base_* ; received and paid
# differ on a Pay entry carrying exchange or bank charges, so each direction
# reads the field that actually describes it.
DIRECTION = {
    "recebimentos": ("Receive", "Customer", "base_received_amount", "received from customers"),
    "pagamentos": ("Pay", "Supplier", "base_paid_amount", "paid to suppliers"),
}


@ai_tool(
    name="recebimentos_pagamentos",
    description=(
        "Money that actually moved in a period: receipts banked from customers, or payments "
        "made to suppliers, by party and by payment method. Use for 'how much did we "
        "collect', 'what did we receive this week', 'what have we paid out', 'quanto "
        "recebemos', 'quanto pagamos', 'cobrancas'. This is NOT contas_a_receber or "
        "contas_a_pagar - those are what is owed, this is what was settled. A general "
        "ledger extract cannot answer it."
    ),
    params={
        "from_date": Param.date("Start of the period."),
        "to_date": Param.date("End of the period."),
        "direccao": Param.enum(
            "Which way the money went.", ["recebimentos", "pagamentos"]),
        "party": Param.text("Restrict to one customer or supplier (exact code).", optional=True),
        "agrupar": Param.boolean(
            "If true (the default), one row per party. If false, list the individual "
            "payment documents.", optional=True),
        "limite": Param.integer("Maximum rows. Default 30.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Payment Entry"],
    group="tesouraria",
)
def recebimentos_pagamentos(from_date, to_date, direccao="recebimentos", party=None,
                            agrupar=True, limite=30, company=None):
    company = resolve_company(company)
    limite = max(1, min(int(limite or 30), 200))
    kind, party_type, amount_field, phrase = DIRECTION.get(
        direccao, DIRECTION["recebimentos"])

    filters = submitted({"company": company, "payment_type": kind,
                         "party_type": party_type})
    filters["posting_date"] = ["between", [from_date, to_date]]
    if party:
        filters["party"] = party

    total, documents, parties = grand_total(
        "Payment Entry", filters, amount_field, group_field="party")

    if agrupar:
        rows = fetch(
            "Payment Entry",
            fields=["party", "party_name",
                    "sum(%s) as valor" % amount_field,
                    "count(name) as documentos",
                    "max(posting_date) as ultimo"],
            filters=filters, group_by="party", order_by="valor desc", limit=limite,
        )
        columns = [text("party", "Code"), text("party_name", "Name"),
                   currency("valor", "Amount"), integer("documentos", "Payments"),
                   date("ultimo", "Last")]
        links = []
    else:
        rows = fetch(
            "Payment Entry",
            fields=["name", "posting_date", "party", "party_name", "mode_of_payment",
                    "%s as valor" % amount_field, "reference_no"],
            filters=filters, order_by="posting_date desc", limit=limite,
        )
        columns = [text("name", "Payment"), date("posting_date", "Date"),
                   text("party_name", "Party"), text("mode_of_payment", "Method"),
                   currency("valor", "Amount"), text("reference_no", "Reference")]
        links = [{"doctype": "Payment Entry", "name": r["name"],
                  "label": "%s  %s" % (r["name"], r.get("party_name") or "")}
                 for r in rows[:10]]

    note = total_note(total, documents, parties, "payments", "parties",
                      rows=rows, value_key="total")
    if not documents:
        note = ("Nothing was %s between %s and %s. This is an empty result, not a missing "
                "report: no submitted Payment Entry matches." % (phrase, from_date, to_date))

    return ToolResult(
        columns=columns,
        rows=rows,
        links=links,
        source=describe("Payment Entry (submitted, %s)" % kind, company, from_date, to_date,
                        extra={"party": party}),
        filters_applied={"company": company, "from_date": from_date, "to_date": to_date,
                         "direccao": direccao, "party": party},
        note=note,
    )
