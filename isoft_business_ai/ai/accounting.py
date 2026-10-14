"""Ledger arithmetic.

One rule governs everything here: ``is_cancelled = 0``. Nearly a fifth of the
GL Entries on this site are cancelled, so a query that forgets it overstates
every figure it produces — and does so without any sign that it has.

Balances are built by summing GL Entry, not by reading a stored balance, so a
figure can always be traced back to the lines that made it. There are no
opening entries on this site, so a cumulative sum from inception is the real
balance.
"""

from frappe.utils import add_days, flt, getdate, nowdate

import frappe

from isoft_business_ai.ai.query import fetch, fetch_reference

# Sign convention per root type: the side on which an increase is recorded.
DEBIT_POSITIVE = {"Asset", "Expense"}


def live(company, extra=None):
    """Base filters for real, posted ledger lines."""
    out = {"company": company, "is_cancelled": 0}
    out.update(extra or {})
    return out


def accounts(company):
    """Leaf accounts, by name, with the metadata the statements need."""
    # Not fetch(): the display cap would drop most of a 1,700-account chart and
    # every ledger line posted to the accounts it dropped.
    rows = fetch_reference("Account",
                           fields=["name", "account_name", "account_number",
                                   "root_type", "report_type", "account_type",
                                   "is_group"],
                           filters={"company": company, "is_group": 0})
    return {r["name"]: r for r in rows}


def _by_account(company, from_date=None, to_date=None):
    """Debit and credit per account over an optional window."""
    filters = live(company)
    if from_date and to_date:
        filters["posting_date"] = ["between", [from_date, to_date]]
    elif to_date:
        filters["posting_date"] = ["<=", to_date]
    elif from_date:
        filters["posting_date"] = [">=", from_date]

    rows = fetch_reference("GL Entry",
                           fields=["account", "sum(debit) as debit",
                                   "sum(credit) as credit"],
                           filters=filters, group_by="account")
    return {r["account"]: (flt(r["debit"]), flt(r["credit"])) for r in rows}


def signed(root_type, debit, credit):
    """A balance in the direction the account naturally grows."""
    if root_type in DEBIT_POSITIVE:
        return debit - credit
    return credit - debit


def trial_balance(company, from_date, to_date):
    meta = accounts(company)
    opening = _by_account(company, to_date=add_days(getdate(from_date), -1))
    period = _by_account(company, from_date=from_date, to_date=to_date)

    rows = []
    for name in set(list(opening) + list(period)):
        info = meta.get(name)
        if not info:
            continue
        od, oc = opening.get(name, (0.0, 0.0))
        pd, pc = period.get(name, (0.0, 0.0))
        open_bal = od - oc
        close_bal = open_bal + pd - pc
        if not (open_bal or pd or pc or close_bal):
            continue
        rows.append({
            "account": info.get("account_number") or "",
            "name": info["account_name"],
            "root_type": info["root_type"],
            "opening": round(open_bal, 2),
            "debit": round(pd, 2),
            "credit": round(pc, 2),
            "closing": round(close_bal, 2),
        })
    rows.sort(key=lambda r: (r["account"] or "zzz", r["name"]))

    totals = {
        "debit": round(sum(r["debit"] for r in rows), 2),
        "credit": round(sum(r["credit"] for r in rows), 2),
    }
    totals["difference"] = round(totals["debit"] - totals["credit"], 2)
    return rows, totals


def profit_and_loss(company, from_date, to_date):
    meta = accounts(company)
    period = _by_account(company, from_date=from_date, to_date=to_date)

    rows, income, expense = [], 0.0, 0.0
    for name, (debit, credit) in period.items():
        info = meta.get(name)
        if not info or info["root_type"] not in ("Income", "Expense"):
            continue
        amount = signed(info["root_type"], debit, credit)
        if not amount:
            continue
        if info["root_type"] == "Income":
            income += amount
        else:
            expense += amount
        rows.append({
            "account": info.get("account_number") or "",
            "name": info["account_name"],
            "root_type": info["root_type"],
            "amount": round(amount, 2),
        })
    rows.sort(key=lambda r: (r["root_type"], -abs(r["amount"])))
    totals = {
        "income": round(income, 2),
        "expense": round(expense, 2),
        "profit": round(income - expense, 2),
    }
    return rows, totals


def balance_sheet(company, as_on):
    """Assets against liabilities, equity and the profit not yet closed.

    This site posts no year-end closing entries, so income and expense accounts
    still carry every year's result. That accumulated result *is* the retained
    earnings: leaving it out makes the statement miss by the whole profit, which
    is how the first version of this reported a 6.3 bn imbalance.
    """
    meta = accounts(company)
    cumulative = _by_account(company, to_date=as_on)

    rows = []
    by_root = {"Asset": 0.0, "Liability": 0.0, "Equity": 0.0,
               "Income": 0.0, "Expense": 0.0}

    for name, (debit, credit) in cumulative.items():
        info = meta.get(name)
        if not info or info["root_type"] not in by_root:
            continue
        amount = signed(info["root_type"], debit, credit)
        by_root[info["root_type"]] += amount
        if info["root_type"] not in ("Asset", "Liability", "Equity") or not amount:
            continue
        rows.append({
            "account": info.get("account_number") or "",
            "name": info["account_name"],
            "root_type": info["root_type"],
            "amount": round(amount, 2),
        })

    retained = by_root["Income"] - by_root["Expense"]
    if retained:
        rows.append({
            "account": "",
            "name": "Retained earnings (profit not yet closed)",
            "root_type": "Equity",
            "amount": round(retained, 2),
        })

    rows.sort(key=lambda r: (r["root_type"], -abs(r["amount"])))

    totals = {
        "Asset": round(by_root["Asset"], 2),
        "Liability": round(by_root["Liability"], 2),
        "Equity": round(by_root["Equity"] + retained, 2),
        "Retained earnings": round(retained, 2),
    }
    totals["difference"] = round(
        totals["Asset"] - (totals["Liability"] + totals["Equity"]), 2)
    return rows, totals


def cash_position(company, as_on=None):
    """Balance of every bank and cash account, as at a date."""
    as_on = as_on or nowdate()
    rows = fetch_reference("Account",
                           fields=["name", "account_name", "account_number",
                                   "account_type"],
                           filters={"company": company, "is_group": 0,
                                    "account_type": ["in", ["Bank", "Cash"]]})
    if not rows:
        return [], {"total": 0.0}

    balances = _by_account(company, to_date=as_on)
    out, total = [], 0.0
    for r in rows:
        debit, credit = balances.get(r["name"], (0.0, 0.0))
        amount = debit - credit          # bank and cash are asset accounts
        if not amount:
            continue
        total += amount
        out.append({
            "account": r.get("account_number") or "",
            "name": r["account_name"],
            "kind": r["account_type"],
            "balance": round(amount, 2),
        })
    out.sort(key=lambda r: -r["balance"])
    return out, {"total": round(total, 2), "as_on": as_on}


# --------------------------------------------------------------- gross margin

# Account types carry the business meaning; account names and numbers differ
# per chart. A site whose COGS accounts are not typed falls back to nothing
# rather than guessing, and the tool says so.
COGS_TYPES = ("Cost of Goods Sold", "Stock Adjustment")


def margin(company, from_date, to_date):
    """Revenue, cost of sales and gross margin over a window.

    Stock Adjustment is reported beside cost of goods sold rather than inside
    it. On this kind of site a revaluation can be larger than a whole year of
    trading - one has exceeded annual cost of sales by orders of magnitude - and
    folding it into cost of sales turns gross margin into a number about the
    stock count rather than about trading.
    """
    meta = accounts(company)
    period = _by_account(company, from_date=from_date, to_date=to_date)

    revenue = cogs = adjustment = other_expense = 0.0
    for name, (debit, credit) in period.items():
        info = meta.get(name)
        if not info:
            continue
        root = info["root_type"]
        if root == "Income":
            revenue += credit - debit
        elif root == "Expense":
            acct_type = info.get("account_type")
            if acct_type == "Stock Adjustment":
                adjustment += debit - credit
            elif acct_type == "Cost of Goods Sold":
                cogs += debit - credit
            else:
                other_expense += debit - credit

    gross = revenue - cogs
    return {
        "revenue": round(revenue, 2),
        "cogs": round(cogs, 2),
        "gross_profit": round(gross, 2),
        "margin_pct": (round(gross / revenue * 100, 1) if revenue else None),
        "stock_adjustment": round(adjustment, 2),
        "other_expense": round(other_expense, 2),
        "net_profit": round(revenue - cogs - adjustment - other_expense, 2),
        "cogs_accounts_typed": any(
            meta.get(n, {}).get("account_type") in COGS_TYPES
            for n in period if meta.get(n, {}).get("root_type") == "Expense"),
    }


def expense_by_account(company, from_date, to_date):
    """Net expense per leaf account over a window, largest first."""
    meta = accounts(company)
    period = _by_account(company, from_date=from_date, to_date=to_date)
    rows = []
    for name, (debit, credit) in period.items():
        info = meta.get(name)
        if not info or info["root_type"] != "Expense":
            continue
        rows.append({
            "account": name,
            "name": info.get("account_name") or name,
            "amount": round(debit - credit, 2),
        })
    rows.sort(key=lambda r: -abs(r["amount"]))
    return rows


# ------------------------------------------------------- Balancete Geral (PGC)
#
# The Angolan trial balance, in the shape the finance team already reads in
# Isoft Insights:
#
#   Conta | Descricao | [Saldo Inicial D | C] | Mov. Debito | Mov. Credito |
#   Saldo Debito | Saldo Credito
#
# Two rules make it a balancete rather than a list of accounts. A group account
# carries the rolled-up movement of everything beneath it, and the saldo is the
# net of the two movement columns placed on its NATURAL SIDE - debit if
# positive, credit if negative, never both. After each PGC class (the first
# digit of the account number) come "Soma Liquida" and "Soma Saldos", then the
# same pair for the whole report.
#
# Reimplemented here rather than calling isoft_insights.get_balancete_geral:
# that function gates on the Insights access list rather than on ERPNext
# permissions, and reads the ledger with raw SQL, so a user restricted to a
# subset of accounts would see all of them. Everything below goes through
# fetch_reference, so the usual permission model applies. The figures are
# checked against that report by tests/check_balancete.py.


def _all_accounts(company):
    """Every account of the company, groups included, for the tree."""
    rows = fetch_reference(
        "Account",
        fields=["name", "account_number", "account_name", "is_group",
                "parent_account", "root_type"],
        filters={"company": company},
    )
    return rows


def _split_saldo(net):
    """A net balance on its natural side: positive debit, negative credit."""
    net = round(flt(net), 2)
    if net > 0:
        return net, 0.0
    if net < 0:
        return 0.0, -net
    return 0.0, 0.0


def _balancete_period(company, from_date, to_date):
    """Default the period to the fiscal year holding to_date."""
    end = getdate(to_date or nowdate())
    if from_date:
        start = getdate(from_date)
    else:
        fy = fetch_reference(
            "Fiscal Year",
            fields=["year_start_date"],
            filters={"year_start_date": ["<=", end], "year_end_date": [">=", end]},
            order_by="year_start_date desc",
        )
        start = getdate(fy[0]["year_start_date"]) if fy else getdate("%d-01-01" % end.year)
    if start > end:
        start, end = end, start
    return start, end


def _movements(company, start, end, voucher_type=None, opening=False):
    filters = live(company)
    if voucher_type:
        filters["voucher_type"] = voucher_type
    if opening:
        filters["posting_date"] = ["<", start]
    else:
        filters["posting_date"] = ["between", [start, end]]
    rows = fetch_reference(
        "GL Entry",
        fields=["account", "sum(debit) as debit", "sum(credit) as credit"],
        filters=filters, group_by="account",
    )
    return {r["account"]: (flt(r["debit"]), flt(r["credit"])) for r in rows}


SALDO_FIELDS = ("abertura_debito", "abertura_credito", "mov_debito", "mov_credito",
                "saldo_debito", "saldo_credito")


def balancete(company, from_date=None, to_date=None, include_opening=False,
              only_with_movement=True, nivel=0, voucher_type=None):
    """Balancete Geral rows, class subtotals and grand totals."""
    start, end = _balancete_period(company, from_date, to_date)
    accounts = _all_accounts(company)
    if not accounts:
        return {"rows": [], "totals": {}, "from_date": str(start), "to_date": str(end),
                "depth": 0, "balanced": True}

    by_name = {a["name"]: a for a in accounts}

    def rollup(raw):
        """Push every posted movement up the whole parent chain."""
        totals = {}
        for account, (debit, credit) in raw.items():
            node = by_name.get(account)
            while node:
                bucket = totals.setdefault(node["name"], [0.0, 0.0])
                bucket[0] += debit
                bucket[1] += credit
                node = by_name.get(node.get("parent_account"))
        return totals

    movement = rollup(_movements(company, start, end, voucher_type, opening=False))
    opening = (rollup(_movements(company, start, end, voucher_type, opening=True))
               if include_opening else {})

    children, roots = {}, []
    for acc in accounts:
        parent = (acc.get("parent_account") or "").strip()
        if parent and parent in by_name:
            children.setdefault(parent, []).append(acc)
        else:
            roots.append(acc)

    def sort_key(a):
        return ((a.get("account_number") or "").strip(), a.get("account_name") or "")

    for kids in children.values():
        kids.sort(key=sort_key)
    roots.sort(key=sort_key)

    def figures(acc):
        mov_d, mov_c = movement.get(acc["name"], (0.0, 0.0))
        op_d, op_c = opening.get(acc["name"], (0.0, 0.0))
        ab_d, ab_c = _split_saldo(op_d - op_c)
        net = (op_d - op_c) + (mov_d - mov_c) if include_opening else (mov_d - mov_c)
        sd, sc = _split_saldo(net)
        return {"abertura_debito": ab_d, "abertura_credito": ab_c,
                "mov_debito": round(mov_d, 2), "mov_credito": round(mov_c, 2),
                "saldo_debito": sd, "saldo_credito": sc}

    def moved(acc):
        mov = movement.get(acc["name"])
        if mov and (abs(mov[0]) >= 0.005 or abs(mov[1]) >= 0.005):
            return True
        op = opening.get(acc["name"])
        return bool(op and (abs(op[0]) >= 0.005 or abs(op[1]) >= 0.005))

    rows, deepest = [], [0]

    def emit(acc, level):
        if only_with_movement and not moved(acc):
            return
        deepest[0] = max(deepest[0], level)
        kids = children.get(acc["name"]) or []
        if not nivel or level < nivel:
            rows.append(dict({
                "tipo": "conta",
                "conta": (acc.get("account_number") or "").strip() or acc["name"],
                "descricao": ("  " * level) + (acc.get("account_name") or acc["name"]),
                "nivel": level,
            }, **figures(acc)))
        for kid in kids:
            emit(kid, level + 1)

    def summed(nodes):
        total = dict.fromkeys(SALDO_FIELDS, 0.0)
        for node in nodes:
            vals = figures(node)
            for f in SALDO_FIELDS:
                total[f] = round(total[f] + vals[f], 2)
        return total

    # A single-digit class account is not a row of its own: its children take
    # its place and the Soma lines are its total.
    classes = []
    for root in roots:
        key = ((root.get("account_number") or "").strip()
               or (root.get("account_name") or "?"))[:1]
        is_class_root = len((root.get("account_number") or "").strip()) == 1
        tops = (children.get(root["name"]) or []) if is_class_root else [root]
        if classes and classes[-1]["key"] == key:
            classes[-1]["tops"].extend(tops)
        else:
            classes.append({"key": key, "tops": list(tops)})

    grand_tops = []
    for group in classes:
        tops = sorted(group["tops"], key=sort_key)
        visible = [t for t in tops if not only_with_movement or moved(t)]
        if not visible:
            continue
        before = len(rows)
        for top in visible:
            emit(top, 0)
        if len(rows) == before:
            continue
        grand_tops.extend(visible)
        totals = summed(visible)
        rows.append(dict({"tipo": "soma", "_style": "subtotal", "conta": "", "nivel": 0,
                          "descricao": "Soma Liquida  (classe %s)" % group["key"]},
                         **totals))
        if abs(totals["saldo_debito"]) >= 0.005 or abs(totals["saldo_credito"]) >= 0.005:
            rows.append(dict(
                {"tipo": "soma", "_style": "subtotal", "conta": "", "nivel": 0,
                 "descricao": "Soma Saldos  (classe %s)" % group["key"]},
                **{f: (totals[f] if "saldo" in f or "abertura" in f else None)
                   for f in SALDO_FIELDS}))

    totals = summed(grand_tops)
    if grand_tops:
        rows.append(dict({"tipo": "total", "_style": "total", "conta": "", "nivel": 0,
                          "descricao": "Soma Liquida Geral"}, **totals))
        rows.append(dict({"tipo": "total", "_style": "total", "conta": "", "nivel": 0,
                          "descricao": "Soma Saldos Geral"},
                         **{f: (totals[f] if "saldo" in f or "abertura" in f else None)
                            for f in SALDO_FIELDS}))

    return {
        "rows": rows,
        "totals": totals,
        "from_date": str(start),
        "to_date": str(end),
        "depth": deepest[0] + 1,
        "balanced": abs(totals.get("mov_debito", 0) - totals.get("mov_credito", 0)) < 0.01,
    }
