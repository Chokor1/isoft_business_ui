# -*- coding: utf-8 -*-
"""What the business words mean on this installation.

A field name does not tell you its business meaning, and on this site several
of the obvious readings are wrong in ways that change an answer by tens of
millions. Every entry below records the calculation, where it comes from, and
the evidence it was checked against, so a figure can be traced rather than
trusted.

Verified against the live chart of accounts and ledger. Re-check with
tests/run_gold_set.py --mode tools after any change to the chart of accounts,
the naming of stock accounts, or the custom apps that post to them.
"""

from __future__ import unicode_literals

VERIFIED_ON = "2026-10-09"
VERIFIED_SITE = "the installation this app is deployed on"

TERMS = [
    {
        "term": "Sales, invoiced sales, facturacao",
        "means": "Submitted Sales Invoices, including tax, net of credit notes.",
        "calculation": "sum(Sales Invoice.base_grand_total) where docstatus = 1",
        "tool": "vendas_total",
        "careful": (
            "This is NOT the same as revenue in the ledger. Three figures sit close "
            "together and differ by millions: invoiced including tax, invoiced excluding "
            "tax, and what the GL Income accounts carry. Quoting one against another as a "
            "change over time is the easiest way to produce a wrong story."),
        "evidence": "cross-checked with SQL over tabSales Invoice and tabGL Entry",
    },
    {
        "term": "Revenue (accounting)",
        "means": "Credits less debits on accounts whose root_type is Income, excluding tax.",
        "calculation": "sum(credit - debit) on GL Entry where is_cancelled = 0 and Account.root_type = 'Income'",
        "tool": "financial_statement, margem",
        "careful": "Always excludes output tax. Use this for margin, not invoiced totals.",
        "evidence": "reconciled to the Income root over a full year",
    },
    {
        "term": "Cost of goods sold",
        "means": "Expense accounts typed 'Cost of Goods Sold' on the chart of accounts.",
        "calculation": "sum(debit - credit) on GL Entry for Account.account_type = 'Cost of Goods Sold'",
        "tool": "margem",
        "careful": (
            "Account NAMES differ per chart; the TYPE carries the meaning. Only 2 accounts "
            "are typed this way here. Stock Adjustment is a separate account_type and is "
            "deliberately NOT folded into cost of sales."),
        "evidence": "compared year on year against the typed COGS accounts",
    },
    {
        "term": "Gross profit / gross margin",
        "means": "Revenue less cost of goods sold, and that over revenue.",
        "calculation": "revenue - cogs ; margin% = gross / revenue * 100",
        "tool": "margem",
        "careful": (
            "Not net profit. Net profit here can also carry a large Stock Adjustment, "
            "which is a valuation movement rather than trading - on this kind of site a "
            "single revaluation has exceeded a whole year of cost of sales. Reporting net "
            "profit without naming that movement is misleading."),
        "evidence": "gross margin compared with the same window a year earlier",
    },
    {
        "term": "Outstanding balance, what a customer owes",
        "means": "Unpaid amount still carried on submitted invoices, not a ledger balance.",
        "calculation": "sum(Sales Invoice.outstanding_amount) where docstatus = 1 and outstanding_amount > 0",
        "tool": "contas_a_receber, extrato_cliente",
        "careful": (
            "The threshold is > 0, not > 0.005. Rounding residuals of a thousandth of a "
            "kwanza exist and WILL change an invoice count if you filter them out. They "
            "are residuals, not debts worth chasing - report them, do not hide them."),
        "evidence": "invoice and customer counts reconciled at both thresholds",
    },
    {
        "term": "Overdue",
        "means": "Past its due date as at the reference date, not merely unpaid.",
        "calculation": "due_date < as_on, bucketed 1-30 / 31-60 / 61-90 / over 90 days",
        "tool": "contas_a_receber, contas_a_pagar, facturas_de_compra",
        "careful": "An invoice with no due date is counted as not due, never as overdue.",
        "evidence": "bucket totals reconciled to the grand total",
    },
    {
        "term": "Stock value",
        "means": "The valuation ERPNext holds per item and warehouse, right now.",
        "calculation": "sum(Bin.stock_value) over the company's non-group warehouses",
        "tool": "stock_valor_total, stock_actual, stock_risco",
        "careful": (
            "Bin has no company field; scope is applied by resolving the company's "
            "warehouses first. A 500-row cap over Bin under-reports the total badly - "
            "this has gone wrong twice."),
        "evidence": "Bin total reconciled against a per-warehouse breakdown",
    },
    {
        "term": "Available stock",
        "means": "Physically on hand, which is not the same as free to sell.",
        "calculation": "Bin.actual_qty on hand; Bin.projected_qty allows for reservations and orders",
        "tool": "stock_actual, stock_risco",
        "careful": (
            "Where reservations are small the two read almost the same, which is exactly "
            "when the difference gets forgotten. Say which one you used either way."),
        "evidence": "actual, reserved and projected compared across all warehouses",
    },
    {
        "term": "Slow-moving / dead stock",
        "means": "No OUTWARD stock movement over the window, regardless of receipts.",
        "calculation": "no Stock Ledger Entry with actual_qty < 0 and is_cancelled = 0 in the window",
        "tool": "stock_risco",
        "careful": (
            "Reorder levels are often configured on almost no item, so 'will run out' is "
            "judged from recent consumption rather than from a configured level, and the "
            "tool says which it used."),
        "evidence": "movement verdicts reconciled to a direct SQL count of the same window",
    },
    {
        "term": "Why stock changed",
        "means": "Every document type that moved stock, not purchases alone.",
        "calculation": "Stock Ledger Entry grouped by voucher_type over the period",
        "tool": "stock_movimentos",
        "careful": (
            "Purchases can be a rounding error against it. Stock Entries and "
            "reconciliations have moved three orders of magnitude more value than purchase "
            "receipts in the same year, so attributing a stock rise to purchase invoices "
            "is simply wrong."),
        "evidence": "Stock Ledger Entry grouped by voucher_type over a full year",
    },
    {
        "term": "Balancete Geral",
        "means": ("The Angolan PGC trial balance: movement debit and credit per account, "
                  "and the closing balance split onto its natural side."),
        "calculation": ("saldo = movement debit - movement credit (plus opening when asked); "
                        "positive goes in Saldo debito, negative in Saldo credito, the other "
                        "is 0. Group accounts carry the rolled-up total of their sub-tree."),
        "tool": "balancete_geral",
        "careful": (
            "Not the same shape as financial_statement(trial_balance), which returns opening "
            "and closing as ONE signed number. When someone says 'balancete' they mean the "
            "six-column form with debit and credit kept apart. Each PGC class ends with Soma "
            "Liquida and Soma Saldos; those lines are the totals over every account, not over "
            "the rows displayed."),
        "evidence": ("matches the Isoft Insights Balancete Geral line for line across four "
                     "configurations, with movement debit equal to movement credit"),
    },
    {
        "term": "Cancelled documents",
        "means": "Reversed entries that must never be counted.",
        "calculation": "GL Entry.is_cancelled = 0 ; docstatus = 1 on documents",
        "tool": "every accounting tool",
        "careful": "A fifth of GL Entries on a busy company can be cancelled. Omitting the "
                   "filter inflates every ledger figure.",
        "evidence": "cancelled share measured directly against tabGL Entry",
    },
    {
        "term": "Returns, credit notes, devolucoes",
        "means": "Sales Invoices flagged is_return, carrying negative values.",
        "calculation": "Sales Invoice.is_return = 1 and docstatus = 1",
        "tool": "vendas_total / vendas_por_cliente with apenas_devolucoes",
        "careful": "Sales totals include them by default, so a 'sales' figure is already net.",
        "evidence": "credit-note totals reconciled against is_return on the invoice",
    },
]


def for_prompt():
    """The few definitions that change an answer if the model guesses them."""
    keep = ("Sales, invoiced sales, facturacao", "Revenue (accounting)",
            "Gross profit / gross margin", "Outstanding balance, what a customer owes",
            "Why stock changed", "Cancelled documents")
    out = []
    for t in TERMS:
        if t["term"] in keep:
            out.append("- %s: %s %s" % (t["term"], t["means"], t["careful"]))
    return "\n".join(out)
