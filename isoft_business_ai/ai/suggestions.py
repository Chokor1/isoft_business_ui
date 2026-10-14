# -*- coding: utf-8 -*-
"""Questions worth offering.

Deliberately a curated list rather than text scraped from the tool
descriptions: the descriptions carry bilingual example phrasings aimed at the
*model*, which read as fragments to a person ("quanto vendemos em Julho").
These are whole questions aimed at a person, and each one names the tool it is
meant to reach, so a suggestion the user cannot run is never shown.

Keeping it honest costs one line per new tool. If you add a tool and forget,
the assistant still answers the question — it just stops being suggested.
"""

from __future__ import unicode_literals

import frappe
from frappe import _

# (tool, question). The question is English source; translations/pt.csv carries
# the Portuguese, and _() is applied per request because the language is the
# user's, not the process's.
CATALOGUE = [
    ("vendas_total", "How much did we sell last month?"),
    ("vendas_total", "What have we invoiced this year?"),
    ("vendas_por_periodo", "Show the monthly sales trend this year."),
    ("vendas_por_cliente", "Who are our top 10 customers this year?"),
    ("vendas_por_artigo", "What are our best selling products?"),
    ("facturas_de_venda", "Show unpaid sales invoices."),
    ("sales_pipeline", "What is still open in the pipeline?"),
    ("contas_a_receber", "Who owes us money?"),
    ("contas_a_receber", "Which customers are more than 90 days overdue?"),
    ("contas_a_pagar", "How much do we owe suppliers?"),
    ("extrato_cliente", "Show the statement for a customer."),
    ("compras_total", "How much did we buy this year?"),
    ("compras_total", "Who are our main suppliers?"),
    ("stock_valor_total", "What is our total stock value?"),
    ("stock_actual", "What is in the warehouse?"),
    ("stock_ledger", "How did the stock of an item change?"),
    ("cash_position", "How much cash do we have?"),
    ("financial_statement", "Are we profitable this year?"),
    ("financial_statement", "Show the trial balance for this year."),
    ("financial_statement", "Show the balance sheet."),
    ("general_ledger", "What moved on an account this month?"),
    ("target_progress", "Am I going to hit my target?"),
    ("gap_closers", "How do I close the gap on my target?"),
    ("business_alerts", "Is there anything I should know?"),
]


def available():
    """The catalogue, translated, minus anything this user could not run.

    Permission is decided by the tool's own doctype guard — the same one the
    loop applies before a tool executes — so the suggestion list and what the
    assistant will actually do for you cannot drift apart.
    """
    from isoft_business_ai.ai.registry import TOOL_REGISTRY, load_tools
    from isoft_business_ai.ai.security import guard_doctypes

    load_tools()
    allowed = {}
    out = []
    for tool, question in CATALOGUE:
        spec = TOOL_REGISTRY.get(tool)
        if not spec:
            # A catalogue line left behind by a removed tool. Drop it quietly
            # rather than offering a question nothing can answer.
            continue
        if tool not in allowed:
            try:
                guard_doctypes(spec["doctypes"])
                allowed[tool] = True
            except Exception:
                allowed[tool] = False
        if allowed[tool]:
            out.append({"tool": tool, "group": spec["group"], "text": _(question)})
    return out
