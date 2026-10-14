"""Accounting and ledger tools.

One tool covers the three statements rather than three tools: they share the
same engine, and every tool definition costs tokens on every request.
"""

import frappe
from frappe.utils import add_days, add_years, date_diff, flt, getdate, nowdate

from isoft_business_ai.ai import accounting as engine
from isoft_business_ai.ai.formatting import currency, text
from isoft_business_ai.ai.query import describe, fetch
from isoft_business_ai.ai.registry import MAX_ROWS, Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company


@ai_tool(
    name="financial_statement",
    description=(
        "Trial balance, profit and loss, or balance sheet, built from the general ledger. "
        "Use for 'are we profitable', 'what did we earn', 'show the P&L', 'trial balance', "
        "'balance sheet', 'what are our assets'. Cancelled entries are always excluded."
    ),
    params={
        "kind": Param.enum("Which statement.",
                           ["profit_and_loss", "balance_sheet", "trial_balance"]),
        "from_date": Param.date("Period start. Ignored for a balance sheet.", optional=True),
        "to_date": Param.date("Period end, or the date a balance sheet is drawn at.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry", "Account"],
    group="contabilidade",
)
def financial_statement(kind, from_date=None, to_date=None, company=None):
    company = resolve_company(company)
    to_date = to_date or nowdate()

    if kind == "balance_sheet":
        rows, totals = engine.balance_sheet(company, to_date)
        header = {"As at": to_date, "Assets": totals["Asset"],
                  "Liabilities": totals["Liability"], "Equity": totals["Equity"],
                  "of which retained earnings": totals["Retained earnings"],
                  "Assets less liabilities and equity": totals["difference"]}
        note = ("Cumulative from the first entry; this site records no opening or closing "
                "entries, so the profit that has never been closed is shown as retained "
                "earnings. A non-zero difference means the books do not balance — say so.")
        cols = [text("account", "Code"), text("name", "Account"),
                text("root_type", "Type"), currency("amount", "Balance")]
    elif kind == "profit_and_loss":
        if not from_date:
            frappe.throw("A profit and loss statement needs from_date and to_date.")
        rows, totals = engine.profit_and_loss(company, from_date, to_date)
        header = {"Period": "%s to %s" % (from_date, to_date),
                  "Income": totals["income"], "Expenses": totals["expense"],
                  "Profit": totals["profit"]}
        note = "Income shown as credit less debit, expenses as debit less credit."
        cols = [text("account", "Code"), text("name", "Account"),
                text("root_type", "Type"), currency("amount", "Amount")]
    elif kind == "trial_balance":
        if not from_date:
            frappe.throw("A trial balance needs from_date and to_date.")
        rows, totals = engine.trial_balance(company, from_date, to_date)
        header = {"Period": "%s to %s" % (from_date, to_date),
                  "Total debit": totals["debit"], "Total credit": totals["credit"],
                  "Difference": totals["difference"]}
        note = "Debit and credit totals should match; a difference is worth reporting."
        cols = [text("account", "Code"), text("name", "Account"),
                currency("opening", "Opening"), currency("debit", "Debit"),
                currency("credit", "Credit"), currency("closing", "Closing")]
    else:
        frappe.throw("Unknown statement %r." % kind)

    return ToolResult(
        columns=cols, rows=rows,
        source=describe("GL Entry (not cancelled)", company, from_date, to_date),
        filters_applied={"kind": kind, "company": company},
        header=header, note=note,
    )


@ai_tool(
    name="general_ledger",
    description=(
        "Individual ledger entries with a running balance — for one account, one party, or "
        "everything in a period. Use for 'show the ledger', 'what moved on this account', "
        "'entries for this supplier'. Cancelled entries are excluded."
    ),
    params={
        "from_date": Param.date("Period start."),
        "to_date": Param.date("Period end."),
        "account": Param.text("Restrict to one account (exact name).", optional=True),
        "party": Param.text("Restrict to one customer or supplier code.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'data' is chronological (the default) and is the only order in "
            "which the running balance means anything. 'valor' is the largest debit first "
            "and 'credito' the largest credit first - use those for 'the biggest postings', "
            "and the running balance is dropped because it would be nonsense.",
            ["data", "valor", "credito"], optional=True),
        "limite": Param.integer("Maximum entries. Default 200.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry"],
    group="contabilidade",
)
def general_ledger(from_date, to_date, account=None, party=None, ordenar_por="data",
                   limite=200, company=None):
    company = resolve_company(company)
    filters = engine.live(company, {"posting_date": ["between", [from_date, to_date]]})
    if account:
        filters["account"] = account
    if party:
        filters["party"] = party

    chronological = (ordenar_por or "data") == "data"
    order = {"valor": "debit desc", "credito": "credit desc"}.get(
        ordenar_por or "data", "posting_date asc, creation asc")

    rows = fetch("GL Entry",
                 fields=["posting_date", "account", "party", "voucher_type", "voucher_no",
                         "debit", "credit", "remarks"],
                 filters=filters, order_by=order,
                 limit=min(int(limite or 200), 500))

    columns = [text("posting_date", "Date"), text("account", "Account"),
               text("voucher_type", "Type"), text("voucher_no", "Document"),
               text("party", "Party"), currency("debit", "Debit"),
               currency("credit", "Credit")]

    if chronological:
        balance = 0.0
        for r in rows:
            balance += flt(r.get("debit")) - flt(r.get("credit"))
            r["balance"] = round(balance, 2)
        columns.append(currency("balance", "Running"))
        note = ("The running balance starts at zero on %s and covers only the rows "
                "returned. Chronological order, so this page is NOT a ranking: ask with "
                "ordenar_por='valor' for the biggest postings." % from_date)
    else:
        # A running balance down a value-sorted page would be arithmetic over an
        # arbitrary order, which is worse than not showing it.
        note = ("Sorted by %s, largest first, so there is no running balance - it would be "
                "meaningless outside date order. The %d rows shown are a capped page."
                % ("debit" if ordenar_por == "valor" else "credit", len(rows)))

    return ToolResult(
        columns=columns,
        rows=rows,
        source=describe("GL Entry (not cancelled)", company, from_date, to_date,
                        {"account": account, "party": party, "order": ordenar_por}),
        filters_applied=dict(filters, ordenar_por=ordenar_por),
        note=note,
    )


@ai_tool(
    name="cash_position",
    description=(
        "Balance of every bank and cash account as at a date, with the total. Use for "
        "'how much cash do we have', 'bank balances', 'what is in the accounts'."
    ),
    params={
        "as_on": Param.date("Date to draw balances at. Omit for today.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry", "Account"],
    group="contabilidade",
)
def cash_position(as_on=None, company=None):
    company = resolve_company(company)
    rows, totals = engine.cash_position(company, as_on)
    return ToolResult(
        columns=[text("account", "Code"), text("name", "Account"),
                 text("kind", "Type"), currency("balance", "Balance")],
        rows=rows,
        source=describe("GL Entry on bank and cash accounts", company,
                        extra={"as at": totals["as_on"]}),
        header={"As at": totals["as_on"], "Total cash and bank": totals["total"],
                "Accounts with a balance": len(rows)},
        note="Cumulative from the first entry, cancelled entries excluded.",
    )


@ai_tool(
    name="margem",
    description=(
        "Gross margin for a period: revenue, cost of goods sold, gross profit and margin "
        "percent, optionally against the same window a year earlier. Use this, not the "
        "P&L, for 'are we making money on what we sell', 'why did profitability fall', "
        "'what is our margin', 'margem bruta', 'porque desceu o lucro'."
    ),
    params={
        "from_date": Param.date("Start of the period."),
        "to_date": Param.date("End of the period."),
        "comparar": Param.boolean(
            "If true (the default), also show the same window one year earlier.",
            optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry", "Account"],
    group="contabilidade",
)
def margem(from_date, to_date, comparar=True, company=None):
    company = resolve_company(company)
    current = engine.margin(company, from_date, to_date)

    rows = [dict(current, periodo="%s to %s" % (from_date, to_date))]
    note_bits = []
    if comparar:
        prior_from = add_years(getdate(from_date), -1)
        prior_to = add_years(getdate(to_date), -1)
        prior = engine.margin(company, prior_from, prior_to)
        rows.append(dict(prior, periodo="%s to %s" % (prior_from, prior_to)))

        if current["revenue"] and prior["revenue"]:
            delta = current["revenue"] - prior["revenue"]
            note_bits.append("Revenue moved %s%s year on year."
                             % ("+" if delta >= 0 else "", round(delta, 2)))
        if current["margin_pct"] is not None and prior["margin_pct"] is not None:
            note_bits.append("Gross margin %s%% vs %s%%."
                             % (current["margin_pct"], prior["margin_pct"]))

    if current["stock_adjustment"]:
        note_bits.append(
            "Stock Adjustment of %s is shown separately from cost of goods sold: it is a "
            "valuation movement, not trading cost, and including it would make the margin "
            "a statement about the stock count rather than about selling."
            % current["stock_adjustment"])
    if not current["cogs_accounts_typed"]:
        note_bits.append(
            "No account on this chart is typed 'Cost of Goods Sold', so cost of sales "
            "reads as zero and the margin shown is not reliable. The chart needs the "
            "account type set before this figure means anything.")

    return ToolResult(
        columns=[
            text("periodo", "Period"),
            currency("revenue", "Revenue"),
            currency("cogs", "Cost of goods sold"),
            currency("gross_profit", "Gross profit"),
            text("margin_pct", "Margin %"),
            currency("stock_adjustment", "Stock adjustment"),
            currency("other_expense", "Other expenses"),
            currency("net_profit", "Net profit"),
        ],
        rows=rows,
        source=describe("GL Entry (posted, not cancelled)", company,
                        extra={"period": "%s to %s" % (from_date, to_date)}),
        filters_applied={"company": company, "from_date": from_date, "to_date": to_date},
        note=" ".join(note_bits),
    )


@ai_tool(
    name="despesas_revisao",
    description=(
        "Expenses by account for a period beside the same window a year earlier, biggest "
        "movement first — the starting point for 'are there unusual expenses', 'what "
        "should I review', 'why did costs go up', 'despesas invulgares', 'o que subiu'. "
        "It reports what moved and by how much; it does not judge anything to be an error."
    ),
    params={
        "from_date": Param.date("Start of the period."),
        "to_date": Param.date("End of the period."),
        "comparar_com": Param.enum(
            "Which period to show beside this one. 'ano_anterior' is the same window one "
            "year earlier (the default). 'periodo_anterior' is the window of equal length "
            "immediately before it - use this for 'September versus August'.",
            ["ano_anterior", "periodo_anterior"], optional=True),
        "limite": Param.integer("Maximum accounts listed. Default 25.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry", "Account"],
    group="contabilidade",
)
def despesas_revisao(from_date, to_date, comparar_com="ano_anterior", limite=25,
                     company=None):
    company = resolve_company(company)
    limite = max(1, min(int(limite or 25), 200))

    current = engine.expense_by_account(company, from_date, to_date)
    if comparar_com == "periodo_anterior":
        # The equal-length window ending the day before this one starts, so a
        # month compares with a month and a week with a week.
        span = date_diff(getdate(to_date), getdate(from_date))
        prior_to = add_days(getdate(from_date), -1)
        prior_from = add_days(prior_to, -span)
    else:
        prior_from = add_years(getdate(from_date), -1)
        prior_to = add_years(getdate(to_date), -1)
    prior = {r["account"]: r["amount"]
             for r in engine.expense_by_account(company, prior_from, prior_to)}

    rows = []
    for r in current:
        was = flt(prior.get(r["account"]))
        delta = r["amount"] - was
        rows.append({
            "account": r["account"],
            "name": r["name"],
            "amount": r["amount"],
            "anterior": round(was, 2),
            "variacao": round(delta, 2),
            "variacao_pct": (round(delta / abs(was) * 100, 1) if was else None),
        })

    # Biggest mover first: an account that doubled matters more than the one
    # that is merely large and unchanged.
    rows.sort(key=lambda r: -abs(r["variacao"]))
    total = round(sum(r["amount"] for r in current), 2)
    listed = rows[:limite]

    return ToolResult(
        columns=[
            # The key first: general_ledger needs this exact string, and a
            # column the model cannot see is a column it cannot pass on.
            text("account", "Account code"),
            text("name", "Account"),
            currency("amount", "This period"),
            currency("anterior", "Comparison period"),
            currency("variacao", "Change"),
            text("variacao_pct", "Change %"),
        ],
        rows=listed,
        source=describe("GL Entry (posted, not cancelled), Expense accounts", company,
                        extra={"period": "%s to %s" % (from_date, to_date),
                               "compared with": "%s to %s" % (prior_from, prior_to)}),
        filters_applied={"company": company, "from_date": from_date, "to_date": to_date,
                         "comparar_com": comparar_com},
        note=("Total expense this period: %s across %d accounts; the table lists the %d "
              "largest movements. To see the entries behind one, call general_ledger "
              "with the Account code column verbatim - not the readable name beside it."
              % (total, len(current), len(listed))),
    )


@ai_tool(
    name="glossario",
    description=(
        "What a business term means ON THIS INSTALLATION: the exact calculation, which "
        "tool produces it, and what it is easy to get wrong. Call this when a question "
        "turns on a definition - profit, revenue, outstanding, available stock, overdue, "
        "slow-moving - and you are about to choose between two readings."
    ),
    params={
        "termo": Param.text("Term to look up. Omit for the whole glossary.", optional=True),
    },
    doctypes=[],
    group="contabilidade",
)
def glossario(termo=None):
    from isoft_business_ai.ai import glossary

    needle = (termo or "").strip().lower()
    rows = []
    for t in glossary.TERMS:
        blob = (t["term"] + " " + t["means"] + " " + t["tool"]).lower()
        if needle and needle not in blob:
            continue
        rows.append({
            "termo": t["term"],
            "significado": t["means"],
            "calculo": t["calculation"],
            "ferramenta": t["tool"],
            "cuidado": t["careful"],
            "evidencia": t["evidence"],
        })
    note = ("Definitions verified against %s on %s. If none matched, ask for the whole "
            "glossary with no search term rather than guessing a definition."
            % (glossary.VERIFIED_SITE, glossary.VERIFIED_ON))
    return ToolResult(
        columns=[
            text("termo", "Term"),
            text("significado", "Means"),
            text("calculo", "Calculation"),
            text("ferramenta", "Tool"),
            text("cuidado", "Easy to get wrong"),
            text("evidencia", "Checked against"),
        ],
        rows=rows,
        source="isoft_business_ai/ai/glossary.py",
        note=note,
    )


@ai_tool(
    name="balancete_geral",
    description=(
        "The Angolan Balancete Geral (PGC trial balance), in the layout the finance team "
        "reads: one row per account with movement debit, movement credit, and the closing "
        "balance split onto its natural side - debit OR credit, one of them always zero, "
        "never both. Group accounts carry the rolled-up total of everything beneath them, "
        "and each PGC class ends with Soma Liquida and Soma Saldos. Use for 'balancete', "
        "'balancete geral', 'trial balance with debit and credit columns', 'balancete com "
        "saldos'. Prefer this over financial_statement(trial_balance) whenever the user "
        "says balancete or asks for separate debit and credit balance columns."
    ),
    params={
        "from_date": Param.date(
            "Start of the period. Omit to use the fiscal year holding to_date.",
            optional=True),
        "to_date": Param.date("End of the period. Omit for today.", optional=True),
        "saldo_inicial": Param.boolean(
            "If true, add Saldo Inicial debit/credit columns and carry the opening balance "
            "into the closing saldo. Default false.", optional=True),
        "apenas_com_movimento": Param.boolean(
            "If true (the default), hide accounts with no movement in the period.",
            optional=True),
        "nivel": Param.integer(
            "Depth limit: 1 shows only top-level accounts, 2 adds their children, and so "
            "on. 0 or omitted shows the whole tree.", optional=True),
        "voucher_type": Param.text(
            "Restrict to one document type, e.g. 'Journal Entry', 'Sales Invoice'.",
            optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["GL Entry", "Account", "Fiscal Year"],
    group="contabilidade",
)
def balancete_geral(from_date=None, to_date=None, saldo_inicial=False,
                    apenas_com_movimento=True, nivel=0, voucher_type=None,
                    company=None):
    company = resolve_company(company)
    data = engine.balancete(
        company, from_date=from_date, to_date=to_date,
        include_opening=bool(saldo_inicial),
        only_with_movement=bool(apenas_com_movimento),
        nivel=int(nivel or 0), voucher_type=voucher_type,
    )

    columns = [text("conta", "Conta"), text("descricao", "Descricao")]
    if saldo_inicial:
        columns += [currency("abertura_debito", "Saldo inicial debito"),
                    currency("abertura_credito", "Saldo inicial credito")]
    columns += [
        currency("mov_debito", "Mov. debito"),
        currency("mov_credito", "Mov. credito"),
        currency("saldo_debito", "Saldo debito"),
        currency("saldo_credito", "Saldo credito"),
    ]

    # ToolResult trims from the front at MAX_ROWS, and every Soma line sits at
    # the end - so a chart big enough to hit the cap would lose exactly the
    # totals that make it a balancete. Drop account detail instead, never the
    # sums.
    rows = data["rows"]
    dropped = 0
    if len(rows) > MAX_ROWS:
        sums = [r for r in rows if r["tipo"] != "conta"]
        contas = [r for r in rows if r["tipo"] == "conta"]
        keep = max(0, MAX_ROWS - len(sums))
        dropped = len(contas) - keep
        rows = contas[:keep] + sums

    t = data["totals"]
    bits = [
        "Balancete Geral for %s, %s to %s." % (company, data["from_date"], data["to_date"]),
        "Soma Liquida Geral: debito %s, credito %s."
        % (t.get("mov_debito", 0), t.get("mov_credito", 0)),
        "Soma Saldos Geral: debito %s, credito %s."
        % (t.get("saldo_debito", 0), t.get("saldo_credito", 0)),
    ]
    if not data["balanced"]:
        bits.append(
            "THE MOVEMENT COLUMNS DO NOT BALANCE - difference %s. Report this to the user "
            "as something to investigate; do not present the balancete as if it were sound."
            % round(t.get("mov_debito", 0) - t.get("mov_credito", 0), 2))
    else:
        bits.append("Movement debit equals movement credit, so the period balances.")
    bits.append(
        "Every closing balance sits on one side only: where Saldo debito has a value, "
        "Saldo credito is 0, and the other way round. The totals above are the report's "
        "own - do not add the rows up yourself; the table is a capped page of %d rows."
        % len(data["rows"]))
    if nivel:
        bits.append("Limited to level %d of %d available." % (nivel, data["depth"]))

    if dropped:
        bits.append(
            "%d account lines were dropped to stay inside the %d row display cap; the "
            "Soma lines are the totals over ALL accounts, not over the rows shown. Use "
            "nivel to get a shorter balancete rather than a partial one."
            % (dropped, MAX_ROWS))

    return ToolResult(
        columns=columns,
        rows=rows,
        source=describe("GL Entry (posted, not cancelled) over the company chart of accounts",
                        company, data["from_date"], data["to_date"],
                        extra={"voucher type": voucher_type,
                               "opening balances": "included" if saldo_inicial else "excluded"}),
        filters_applied={"company": company, "from_date": data["from_date"],
                         "to_date": data["to_date"], "nivel": nivel,
                         "voucher_type": voucher_type},
        note=" ".join(bits),
    )
