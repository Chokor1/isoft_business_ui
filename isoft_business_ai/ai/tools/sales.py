"""Sales tools.

Every figure here comes from submitted Sales Invoices in company currency
(``base_*`` fields), net of credit notes unless the caller says otherwise.
That default is the accounting-correct one and is stated in the provenance
line so the user can see which convention produced the number.
"""

import frappe
from frappe.utils import flt, getdate

from isoft_business_ai.ai.formatting import currency, integer, number, text
from isoft_business_ai.ai.query import (MAX_REFERENCE_ROWS, date_range, describe, fetch,
                                        fetch_reference, grand_total, grouped_total,
                                        page_share, submitted, total_note)
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import resolve_company

# Frappe v13 blacklists CONCAT (and IF/IFNULL/COALESCE) in a field list as an
# injection guard, and a DATE_FORMAT mask would smuggle a '%' into the query
# string. So each bucket selects plain numeric parts and the label is assembled
# in Python below.
_PERIOD_SPEC = {
    "dia": {
        "fields": ["posting_date as d"],
        "group_by": "posting_date",
        "order_by": "d asc",
        "label": lambda r: str(r.get("d")),
    },
    "mes": {
        "fields": ["YEAR(posting_date) as y", "MONTH(posting_date) as m"],
        "group_by": "YEAR(posting_date), MONTH(posting_date)",
        "order_by": "y asc, m asc",
        "label": lambda r: "%04d-%02d" % (int(r.get("y") or 0), int(r.get("m") or 0)),
    },
    "trimestre": {
        "fields": ["YEAR(posting_date) as y", "QUARTER(posting_date) as q"],
        "group_by": "YEAR(posting_date), QUARTER(posting_date)",
        "order_by": "y asc, q asc",
        "label": lambda r: "%04d-T%d" % (int(r.get("y") or 0), int(r.get("q") or 0)),
    },
    "ano": {
        "fields": ["YEAR(posting_date) as y"],
        "group_by": "YEAR(posting_date)",
        "order_by": "y asc",
        "label": lambda r: str(int(r.get("y") or 0)),
    },
}


def _returns_filter(incluir_devolucoes, filters, apenas_devolucoes=False):
    if apenas_devolucoes:
        # Returns only. Their totals are negative, which is what makes "how much
        # came back, and from whom" readable without further arithmetic.
        filters["is_return"] = 1
        return filters
    if not incluir_devolucoes:
        filters["is_return"] = 0
    return filters


@ai_tool(
    name="vendas_total",
    description=(
        "Total invoiced sales for a period: total value, invoice count and average ticket. "
        "Use for 'how much did we sell in July', 'what was last year's revenue', "
        "'quanto vendemos em Julho', 'qual foi a facturacao'."
    ),
    params={
        "from_date": Param.date("Start date of the period."),
        "to_date": Param.date("End date of the period."),
        "company": Param.text("Company. Omitir para usar a empresa por omissao do utilizador.", optional=True),
        "apenas_devolucoes": Param.boolean(
            "If true, total ONLY credit notes / returns for the period. Use this for "
            "'how much was returned'. The value is negative.", optional=True),
        "incluir_devolucoes": Param.boolean(
            "If true (the default), subtract credit notes, giving net sales.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def vendas_total(from_date, to_date, company=None, incluir_devolucoes=True,
                 apenas_devolucoes=False):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    filters = _returns_filter(incluir_devolucoes, filters,
                              apenas_devolucoes=apenas_devolucoes)

    rows = fetch(
        "Sales Invoice",
        fields=[
            "sum(base_grand_total) as total",
            "sum(base_net_total) as total_sem_impostos",
            "count(name) as facturas",
        ],
        filters=filters,
    )
    row = rows[0] if rows else {}
    total = row.get("total") or 0
    facturas = row.get("facturas") or 0
    row["ticket_medio"] = (total / facturas) if facturas else 0

    return ToolResult(
        columns=[
            currency("total", "Total invoiced"),
            currency("total_sem_impostos", "Total excl. tax"),
            integer("facturas", "Invoices"),
            currency("ticket_medio", "Average ticket"),
        ],
        rows=[row] if row else [],
        source=describe("Sales Invoice (submitted)", company, from_date, to_date,
                        {"returns": "included" if incluir_devolucoes else "excluded"}),
        filters_applied=filters,
    )


def _every_period(agrupar_por, from_date, to_date):
    """Every period label in a range, including the ones with no sales.

    A month with no invoices simply did not come back from a GROUP BY, so a
    twelve-month request produced ten rows and the reader could not tell a
    quiet month from a missing one. Asked for "all the year, per month", that
    is the difference between a complete answer and an incomplete one.
    """
    start, end = getdate(from_date), getdate(to_date)
    out = []
    if agrupar_por == "mes":
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            out.append("%04d-%02d" % (y, m))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    elif agrupar_por == "trimestre":
        y, q = start.year, (start.month - 1) // 3 + 1
        while (y, q) <= (end.year, (end.month - 1) // 3 + 1):
            out.append("%04d-T%d" % (y, q))
            y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    elif agrupar_por == "ano":
        out = [str(y) for y in range(start.year, end.year + 1)]
    return out


@ai_tool(
    name="vendas_por_periodo",
    description=(
        "Sales over time, grouped by day, month, quarter or year. Use for trends and "
        "period-over-period comparisons. 'sales trend', 'monthly sales', 'evolucao das "
        "vendas', 'vendas por trimestre'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "agrupar_por": Param.enum("Granularity of the series.", ["dia", "mes", "trimestre", "ano"]),
        "company": Param.text("Company.", optional=True),
        "incluir_devolucoes": Param.boolean("Subtract credit notes. Default true.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def vendas_por_periodo(from_date, to_date, agrupar_por="mes", company=None, incluir_devolucoes=True):
    company = resolve_company(company)
    spec = _PERIOD_SPEC.get(agrupar_por)
    if not spec:
        frappe.throw("Invalid agrupar_por. Use: dia, mes, trimestre, ano.")

    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    filters = _returns_filter(incluir_devolucoes, filters)

    raw = fetch(
        "Sales Invoice",
        fields=spec["fields"] + ["sum(base_grand_total) as total", "count(name) as facturas"],
        filters=filters,
        group_by=spec["group_by"],
        order_by=spec["order_by"],
    )

    found = {}
    for r in raw:
        found[spec["label"](r)] = {
            "periodo": spec["label"](r),
            "total": r.get("total"),
            "facturas": r.get("facturas"),
        }

    # Periods with nothing in them are listed as zero rather than left out, so
    # a series has no holes for the reader to misread as missing data.
    sequence = _every_period(agrupar_por, from_date, to_date)
    if sequence:
        rows = [found.get(label, {"periodo": label, "total": 0.0, "facturas": 0})
                for label in sequence]
        empty = sum(1 for r in rows if not r["facturas"])
    else:
        rows = list(found.values())
        empty = 0

    # The listed rows are a capped page; this total is not.
    _total, _n, _g = grand_total("Sales Invoice", filters, "base_grand_total")
    _note = total_note(_total, _n, 0, "sales invoices", "")
    if empty:
        _note += (" %d of the %d periods shown had no invoices at all; they are listed "
                  "as zero so the series is complete." % (empty, len(rows)))

    return ToolResult(
        columns=[text("periodo", "Period"), currency("total", "Total"), integer("facturas", "Invoices")],
        rows=rows,
        source=describe("Sales Invoice (submitted)", company, from_date, to_date,
                        {"grouped by": agrupar_por}),
        filters_applied=filters,
        note=_note,
    )


@ai_tool(
    name="vendas_por_cliente",
    description=(
        "Ranking of customers by invoiced value in a period. Use for 'best customers', "
        "'top 10 customers', 'who bought the most', 'melhores clientes', 'quem comprou mais'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "limite": Param.integer("How many customers to return. Default 20.", optional=True),
        "customer_group": Param.text("Filter by customer group.", optional=True),
        "apenas_devolucoes": Param.boolean(
            "If true, list ONLY credit notes / returns, to see what came back and from "
            "whom. The values are negative.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'valor' is largest first (best customers, the default). "
            "'valor_asc' is smallest first. 'facturas' and 'facturas_asc' rank by how many "
            "invoices rather than by value.",
            ["valor", "valor_asc", "facturas", "facturas_asc"], optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def vendas_por_cliente(from_date, to_date, limite=20, customer_group=None,
                       apenas_devolucoes=False, ordenar_por="valor", company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    filters = _returns_filter(True, filters, apenas_devolucoes=apenas_devolucoes)
    if customer_group:
        filters["customer_group"] = customer_group

    rows = fetch(
        "Sales Invoice",
        fields=[
            "customer",
            "customer_name",
            "sum(base_grand_total) as total",
            "count(name) as facturas",
        ],
        filters=filters,
        group_by="customer",
        order_by={"valor": "total desc", "valor_asc": "total asc",
                  "facturas": "facturas desc",
                  "facturas_asc": "facturas asc"}.get(ordenar_por or "valor", "total desc"),
        limit=limite or 20,
    )
    # The listed rows are a capped page; this total is not.
    _total, _n, _g = grand_total("Sales Invoice", filters, "base_grand_total",
                                 group_field="customer")
    _note = total_note(_total, _n, _g, "sales invoices", "customers",
                       rows=rows, value_key="total")
    return ToolResult(
        columns=[
            text("customer", "Customer"),
            text("customer_name", "Name"),
            currency("total", "Total invoiced"),
            integer("facturas", "Invoices"),
        ],
        rows=rows,
        source=describe("Sales Invoice (submitted)", company, from_date, to_date,
                        {"group": customer_group}),
        filters_applied=filters,
        note=_note,
    )


@ai_tool(
    name="vendas_por_artigo",
    description=(
        "Ranking of items/products by value or quantity sold in a period, optionally for "
        "ONE customer. The customer filter is the only way to break a customer's purchases "
        "down to item level - use it for 'what did this customer buy', 'what does X order "
        "from us', 'o que este cliente comprou'. Also use for 'best selling products', "
        "'what do we sell most', 'produtos mais vendidos'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "limite": Param.integer("How many items to return. Default 20.", optional=True),
        "item_group": Param.text("Filter by item group.", optional=True),
        "tipo_artigo": Param.enum(
            "Which kind of item to count: 'todos' (the default), 'stock' for physical "
            "stocked items only, or 'servico' for services and other non-stock items. "
            "Use 'stock' for 'physical items', 'artigos fisicos', 'only what we hold in "
            "stock' - services are often a large share of the value and change the "
            "ranking completely.",
            ["todos", "stock", "servico"], optional=True),
        "customer": Param.text(
            "Restrict to ONE customer (exact customer code). Call procurar_cliente first "
            "if you only know the name.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'valor' and 'quantidade' are largest first (best sellers); "
            "'valor_asc' and 'quantidade_asc' are smallest first - use those for 'worst "
            "selling', 'slowest movers', 'what barely sells'. Never read the bottom of a "
            "descending page as the worst.",
            ["valor", "quantidade", "valor_asc", "quantidade_asc"], optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice", "Sales Invoice Item"],
    group="vendas",
)
def vendas_por_artigo(from_date, to_date, limite=20, item_group=None, customer=None, tipo_artigo=None,
                      ordenar_por="valor", company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    if item_group:
        filters["`tabSales Invoice Item`.item_group"] = item_group
    if customer:
        filters["customer"] = customer
    if tipo_artigo in ("stock", "servico"):
        # is_stock_item lives on Item, which is not a child table of the
        # invoice, so the query builder cannot join it - and a backtick
        # qualified key with an "in" list comes back mis-prefixed. So the whole
        # ranking is built here instead: read every item invoiced in the period
        # uncapped, keep the kind that was asked for, and rank what is left.
        # Only this branch does that; without tipo_artigo nothing changes.
        every = fetch_reference(
            "Sales Invoice",
            fields=["`tabSales Invoice Item`.item_code as item_code",
                    "`tabSales Invoice Item`.item_name as item_name",
                    "sum(`tabSales Invoice Item`.base_net_amount) as valor",
                    "sum(`tabSales Invoice Item`.stock_qty) as quantidade"],
            filters=filters, group_by="`tabSales Invoice Item`.item_code",
            extra_doctypes=["Sales Invoice Item"])
        codes = [r["item_code"] for r in every if r.get("item_code")]
        keep = set(r["name"] for r in frappe.get_all(
            "Item", filters={"name": ["in", codes],
                             "is_stock_item": 1 if tipo_artigo == "stock" else 0},
            fields=["name"], limit_page_length=0)) if codes else set()
        chosen = [r for r in every if r["item_code"] in keep]

        kind_word = "stocked" if tipo_artigo == "stock" else "non-stock"
        if not chosen:
            return ToolResult(
                columns=[text("item_code", "Code")], rows=[],
                source=describe("Sales Invoice Item (submitted invoices)", company,
                                from_date, to_date, {"kind": tipo_artigo}),
                filters_applied=filters,
                note=("No %s item appears in sales for this period, so there is "
                      "nothing to rank. Say that; do not fall back to all items."
                      % kind_word))

        reverse = not (ordenar_por or "valor").endswith("_asc")
        key = "quantidade" if (ordenar_por or "").startswith("quantidade") else "valor"
        chosen.sort(key=lambda r: flt(r.get(key)), reverse=reverse)
        shown = chosen[: limite or 20]
        total = round(sum(flt(r.get("valor")) for r in chosen), 2)
        note = ("Grand total over the %d %s items invoiced in this period: %s net. "
                "%d of the %d items invoiced were %s; the rest are excluded. %s"
                % (len(chosen), kind_word, total, len(chosen), len(every), kind_word,
                   page_share(shown, "valor", total)))
        note += (" These are line values, NET OF TAX. Do not compare them with an "
                 "invoiced total that includes tax.")
        return ToolResult(
            columns=[text("item_code", "Code"), text("item_name", "Item"),
                     currency("valor", "Value sold"), number("quantidade", "Quantity")],
            rows=shown,
            source=describe("Sales Invoice Item (submitted invoices)", company, from_date, to_date,
                            {"item group": item_group, "customer": customer,
                             "kind": tipo_artigo, "ordered by": ordenar_por}),
            filters_applied=filters,
            note=note,
        )

    order = {
        "valor": "valor desc",
        "quantidade": "quantidade desc",
        "valor_asc": "valor asc",
        "quantidade_asc": "quantidade asc",
    }.get(ordenar_por or "valor", "valor desc")
    rows = fetch(
        "Sales Invoice",
        fields=[
            "`tabSales Invoice Item`.item_code as item_code",
            "`tabSales Invoice Item`.item_name as item_name",
            "sum(`tabSales Invoice Item`.base_net_amount) as valor",
            "sum(`tabSales Invoice Item`.stock_qty) as quantidade",
        ],
        filters=filters,
        group_by="`tabSales Invoice Item`.item_code",
        order_by=order,
        limit=limite or 20,
        extra_doctypes=["Sales Invoice Item"],
    )
    # The listed rows are a capped page; this total is not.
    # The figure lives on the child table, so the total comes from reading
    # every item group uncapped rather than from one SUM. The parent's
    # base_net_total is NOT a substitute: on this site it differs from the sum
    # of its own lines by 500.00 over 2026, so it would quietly disagree with
    # the table above it.
    _total, _g, _complete = grouped_total(
        "Sales Invoice",
        fields=["`tabSales Invoice Item`.item_code as item_code",
                "sum(`tabSales Invoice Item`.base_net_amount) as valor"],
        filters=filters,
        group_by="`tabSales Invoice Item`.item_code",
        value_key="valor",
        extra_doctypes=["Sales Invoice Item"])
    _note = ("Grand total over everything these filters match: %s net across %d items. "
             "The table is a capped page of that set - do not add its rows up yourself. %s"
             % (round(_total, 2), _g, page_share(rows, "valor", _total)))
    # An item figure is net of tax, because tax is charged on the invoice and
    # not on the line. Asked for a total and then "by item", a reader sees two
    # different numbers for what looks like the same question - here they
    # differed by the whole tax charge - so the bridge is stated rather than
    # left for them to work out.
    _note += _tax_bridge(filters, item_group, tipo_artigo, _total)
    if not _complete:
        _note += (" More items matched than this total could read, so it is a floor, "
                  "not the full figure.")

    return ToolResult(
        columns=[
            text("item_code", "Code"),
            text("item_name", "Item"),
            currency("valor", "Value sold"),
            number("quantidade", "Quantity"),
        ],
        rows=rows,
        source=describe("Sales Invoice Item (submitted invoices)", company, from_date, to_date,
                        {"item group": item_group, "customer": customer,
                         "kind": tipo_artigo,
                         "ordered by": ordenar_por}),
        filters_applied=filters,
        note=_note,
    )


ORDER_BY = {
    "data": "posting_date desc, name desc",
    "data_asc": "posting_date asc, name asc",
    "valor": "base_grand_total desc",
    "valor_asc": "base_grand_total asc",
    "em_divida": "outstanding_amount desc",
}


@ai_tool(
    name="facturas_de_venda",
    description=(
        "Lists individual sales invoices for a period, optionally for one customer or one "
        "status, sorted by date or by value. Use when the user wants to see the documents "
        "rather than a total, and set ordenar_por='valor' for any 'biggest', 'largest' or "
        "'top N invoices by amount' question - the default date order is NOT a ranking. "
        "'show me the invoices', 'unpaid invoices', 'the 20 largest invoices', "
        "'mostra as facturas', 'facturas por pagar', 'as maiores facturas'."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "customer": Param.text("Exact customer code. Use procurar_cliente first if you only know the name.", optional=True),
        "estado": Param.enum("Filter by invoice status.",
                             ["Paid", "Unpaid", "Overdue", "Return", "Credit Note Issued", "Partly Paid"],
                             optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'data' is newest first (the default). 'valor' is largest value "
            "first - use it for 'top N by amount'. 'data_asc' is OLDEST first, for 'the "
            "oldest invoice'. 'em_divida' is largest unpaid balance first. 'valor_asc' is "
            "smallest first, for credit notes and returns.",
            ["data", "data_asc", "valor", "em_divida", "valor_asc"], optional=True),
        "apenas_em_aberto": Param.boolean(
            "If true, only invoices that still carry a balance, whatever their status. Use "
            "this for 'still unpaid' and 'with a balance' - the estado filter matches one "
            "exact status, so estado='Unpaid' silently excludes everything Overdue.",
            optional=True),
        "valor_minimo": Param.number(
            "Only invoices at or above this value. Useful with ordenar_por='valor'.",
            optional=True),
        "limite": Param.integer("Maximum invoices. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def facturas_de_venda(from_date, to_date, customer=None, estado=None,
                      ordenar_por="data", valor_minimo=None, apenas_em_aberto=False,
                      limite=50, company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    if customer:
        filters["customer"] = customer
    if estado:
        filters["status"] = estado
    if valor_minimo is not None:
        filters["base_grand_total"] = [">=", flt(valor_minimo)]
    if apenas_em_aberto:
        filters["outstanding_amount"] = [">", 0]

    order = ORDER_BY.get(ordenar_por or "data", ORDER_BY["data"])
    rows = fetch(
        "Sales Invoice",
        fields=["name", "posting_date", "customer", "customer_name", "base_grand_total",
                "outstanding_amount", "status", "due_date"],
        filters=filters,
        order_by=order,
        limit=limite or 50,
    )
    # The listed rows are a capped page; this total is not.
    _total, _n, _g = grand_total("Sales Invoice", filters, "base_grand_total",
                                 group_field="customer")
    _note = total_note(_total, _n, _g, "sales invoices", "customers",
                       rows=rows, value_key="total")
    # Say what the order is, so a date-ordered page is never read as a ranking.
    _note += {
        "valor": " Sorted by value, largest first, so these ARE the largest invoices.",
        "valor_asc": " Sorted by value, smallest first - credit notes and returns lead.",
        "em_divida": " Sorted by unpaid balance, largest first.",
        "data_asc": " Sorted by date, OLDEST first.",
    }.get(ordenar_por or "data",
          " Sorted by date, newest first. This is NOT a ranking by value: ask again with "
          "ordenar_por='valor' for the largest invoices.")


    return ToolResult(
        columns=[
            text("name", "Invoice"),
            text("posting_date", "Date"),
            text("customer_name", "Customer"),
            currency("base_grand_total", "Total"),
            currency("outstanding_amount", "Outstanding"),
            text("status", "Status"),
            text("due_date", "Due date"),
        ],
        rows=rows,
        source=describe("Sales Invoice (submitted)", company, from_date, to_date,
                        {"customer": customer, "status": estado}),
        filters_applied=dict(filters, ordenar_por=ordenar_por),
        note=_note,
    )


@ai_tool(
    name="clientes_inactivos",
    description=(
        "Customers who bought in one period and nothing at all in a later one: lapsed or "
        "lost customers. Use for 'who stopped buying', 'customers we lost', 'who bought "
        "last year but not this year', 'clientes que deixaram de comprar', 'clientes "
        "inactivos'. Do NOT try to answer this by comparing two ranked sales lists - "
        "neither list is complete and the comparison cannot be done by reading them."
    ),
    params={
        "from_date": Param.date("Start of the period they DID buy in (e.g. last year)."),
        "to_date": Param.date("End of the period they DID buy in."),
        "desde": Param.date(
            "Start of the period they bought NOTHING in - normally the day after to_date."),
        "ate": Param.date("End of the period they bought nothing in, normally today."),
        "limite": Param.integer("Maximum customers listed. Default 50.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def clientes_inactivos(from_date, to_date, desde, ate, limite=50, company=None):
    company = resolve_company(company)

    def buyers(start, end):
        """Every customer with submitted sales in a window, uncapped."""
        filters = submitted({"company": company})
        filters.update(date_range("posting_date", start, end))
        rows = fetch_reference(
            "Sales Invoice",
            fields=["customer", "customer_name",
                    "sum(base_grand_total) as total", "count(name) as facturas",
                    "max(posting_date) as ultima"],
            filters=filters,
            group_by="customer",
            order_by="total desc")
        return {r["customer"]: r for r in rows}

    before = buyers(from_date, to_date)
    after = buyers(desde, ate)

    # The set difference is done here, on two complete lists. Reading it off two
    # capped ranked pages is what makes this question unanswerable otherwise.
    lapsed = [r for code, r in before.items() if code not in after]
    lapsed.sort(key=lambda r: -flt(r.get("total")))
    lost_value = sum(flt(r.get("total")) for r in lapsed)

    rows = [{
        "customer": r["customer"],
        "customer_name": r.get("customer_name"),
        "total": flt(r.get("total")),
        "facturas": int(r.get("facturas") or 0),
        "ultima": r.get("ultima"),
    } for r in lapsed[: max(1, int(limite or 50))]]

    header = {
        "Bought in": "%s to %s" % (from_date, to_date),
        "Bought nothing in": "%s to %s" % (desde, ate),
        "Customers in the first period": len(before),
        "Still buying": len(before) - len(lapsed),
        "Stopped buying": len(lapsed),
        "Their value in the first period": round(lost_value, 2),
    }
    note = ("%d of the %d customers who bought between %s and %s have no submitted sales "
            "invoice at all between %s and %s. They were worth %s in the first period. "
            "Both customer lists were read in full, so these counts are complete; the "
            "table lists the %d largest."
            % (len(lapsed), len(before), from_date, to_date, desde, ate,
               round(lost_value, 2), len(rows)))
    if not lapsed:
        note = ("Every one of the %d customers who bought between %s and %s has bought "
                "again between %s and %s. Nobody lapsed."
                % (len(before), from_date, to_date, desde, ate))

    return ToolResult(
        columns=[
            text("customer", "Code"),
            text("customer_name", "Customer"),
            currency("total", "Value in the first period"),
            integer("facturas", "Invoices then"),
            text("ultima", "Last invoice"),
        ],
        rows=rows,
        source=describe("Sales Invoice (submitted)", company, from_date, to_date,
                        {"compared against": "%s to %s" % (desde, ate)}),
        filters_applied={"company": company, "from_date": from_date, "to_date": to_date,
                         "desde": desde, "ate": ate},
        header=header,
        note=note,
    )


@ai_tool(
    name="vendas_por_utilizador",
    description=(
        "Sales grouped by the person in the system who raised the invoice, not by the "
        "customer who bought. Use for 'sales by user', 'who sold the most', 'sales per "
        "salesperson', 'vendas por utilizador', 'quem vendeu mais', 'por vendedor'. "
        "Every other sales tool groups by customer, item, period or document; this is "
        "the only one that answers for the people doing the selling."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "limite": Param.integer("Maximum people listed. Default 20.", optional=True),
        "ordenar_por": Param.enum(
            "Sort order. 'valor' is most sold first (the default); 'valor_asc' is least "
            "first; 'facturas' is most invoices first.",
            ["valor", "valor_asc", "facturas"], optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice"],
    group="vendas",
)
def vendas_por_utilizador(from_date, to_date, limite=20, ordenar_por="valor", company=None):
    company = resolve_company(company)
    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))

    order = {"valor": "total desc", "valor_asc": "total asc",
             "facturas": "facturas desc"}.get(ordenar_por or "valor", "total desc")
    rows = fetch(
        "Sales Invoice",
        fields=["owner", "sum(base_grand_total) as total", "count(name) as facturas"],
        filters=filters, group_by="owner", order_by=order, limit=limite or 20)

    # The email identifies them but does not read as a name in a report, and a
    # user's own name is not confidential to colleagues who share the company.
    names = {}
    if rows:
        for u in frappe.get_all("User", filters={"name": ["in", [r["owner"] for r in rows]]},
                                fields=["name", "full_name"], limit_page_length=0):
            names[u["name"]] = u.get("full_name")
    for r in rows:
        r["nome"] = names.get(r["owner"]) or r["owner"]

    _total, _n, _g = grand_total("Sales Invoice", filters, "base_grand_total",
                                 group_field="owner")
    note = total_note(_total, _n, _g, "sales invoices", "people",
                      rows=rows, value_key="total")
    note += (" This is who raised each invoice in the system, which is not always who "
             "closed the sale - say so if it matters to the question.")

    return ToolResult(
        columns=[
            text("nome", "Person"),
            text("owner", "User"),
            currency("total", "Total sold"),
            integer("facturas", "Invoices"),
        ],
        rows=rows,
        source=describe("Sales Invoice (submitted, grouped by the user who raised it)",
                        company, from_date, to_date, {"ordered by": ordenar_por}),
        filters_applied=filters,
        note=note,
    )


def _tax_bridge(filters, item_group, tipo_artigo, net_total=0.0):
    """How an item total relates to the invoiced total, in words.

    Only when nothing item-level has been filtered out: otherwise the invoices
    behind the two figures are not the same set and the sentence would be a
    lie.
    """
    if item_group or tipo_artigo in ("stock", "servico"):
        return (" This figure is net of tax. An invoiced total including tax is not "
                "comparable with it, because tax is charged per invoice, not per line.")
    parent_filters = dict((k, v) for k, v in filters.items() if not k.startswith("`"))
    invoiced, _count, _groups = grand_total(
        "Sales Invoice", parent_filters, "base_grand_total")
    if not invoiced:
        return ""
    return (" This is NET OF TAX. The same invoices come to %s including tax, a "
            "difference of %s which is the tax charged. If the reader has just been "
            "given the invoiced total, say which of the two this is and why they "
            "differ." % (round(invoiced, 2), round(invoiced - net_total, 2)))


MAX_PERIOD_COLUMNS = 24


@ai_tool(
    name="vendas_por_artigo_periodo",
    description=(
        "Sales of each item broken down by period - a cross-tab with one row per item "
        "and one column per month, quarter or year. Use whenever both dimensions are "
        "asked for at once: 'sales by item and month', 'items per month', 'a sales "
        "report for items per months', 'vendas por artigo e mes', 'quanto vendemos de "
        "cada artigo em cada mes'. vendas_por_artigo gives items with no period and "
        "vendas_por_periodo gives periods with no items; neither can answer this, and "
        "the two cannot be combined by reading them side by side."
    ),
    params={
        "from_date": Param.date("Start date."),
        "to_date": Param.date("End date."),
        "agrupar_por": Param.enum(
            "Period for the columns: 'mes' (the default), 'trimestre' or 'ano'.",
            ["mes", "trimestre", "ano"], optional=True),
        "medida": Param.enum(
            "What each cell holds: 'valor' for money sold (the default) or "
            "'quantidade' for units sold. Use 'quantidade' for 'by qty', 'how many "
            "did we sell', 'por quantidade'.",
            ["valor", "quantidade"], optional=True),
        "limite": Param.integer(
            "How many items to list, the largest first. Default 20.", optional=True),
        "item_group": Param.text("Restrict to one item group.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Sales Invoice", "Sales Invoice Item"],
    group="vendas",
)
def vendas_por_artigo_periodo(from_date, to_date, agrupar_por="mes", medida="valor",
                              limite=20, item_group=None, company=None):
    company = resolve_company(company)
    agrupar_por = agrupar_por or "mes"
    if agrupar_por not in ("mes", "trimestre", "ano"):
        frappe.throw("Use agrupar_por mes, trimestre or ano for a cross-tab.")

    periods = _every_period(agrupar_por, from_date, to_date)
    if len(periods) > MAX_PERIOD_COLUMNS:
        frappe.throw(
            "That range is %d %s columns wide, which is unreadable. Narrow the dates "
            "or group by a longer period." % (len(periods), agrupar_por))

    def label_of(value):
        day = getdate(value)
        if agrupar_por == "mes":
            return "%04d-%02d" % (day.year, day.month)
        if agrupar_por == "trimestre":
            return "%04d-T%d" % (day.year, (day.month - 1) // 3 + 1)
        return str(day.year)

    filters = submitted({"company": company})
    filters.update(date_range("posting_date", from_date, to_date))
    if item_group:
        filters["`tabSales Invoice Item`.item_group"] = item_group

    # Grouped by item and by the plain posting_date, with the bucketing done
    # here. YEAR(posting_date) cannot be used once the child table is joined:
    # the query builder qualifies bare columns with the parent table and reads
    # a function wrapping a qualified one as a doctype name.
    #
    # Reference-shaped because the cross-tab has to be built from the whole
    # set: a capped page would put an item's March in and leave its April out,
    # and every row total would then be wrong.
    raw = fetch_reference(
        "Sales Invoice",
        fields=["`tabSales Invoice`.posting_date as d",
                "`tabSales Invoice Item`.item_code as item_code",
                "`tabSales Invoice Item`.item_name as item_name",
                "sum(`tabSales Invoice Item`.%s) as valor"
                % ("stock_qty" if medida == "quantidade" else "base_net_amount")],
        filters=filters,
        group_by="`tabSales Invoice Item`.item_code, `tabSales Invoice`.posting_date",
        extra_doctypes=["Sales Invoice Item"])
    complete = len(raw) < MAX_REFERENCE_ROWS

    by_item, column_totals = {}, dict((p, 0.0) for p in periods)
    for r in raw:
        code = r.get("item_code")
        if not code:
            continue
        label = label_of(r.get("d"))
        row = by_item.setdefault(code, {
            "item_code": code, "item_name": r.get("item_name"), "total": 0.0})
        for p in periods:
            row.setdefault(p, 0.0)
        value = flt(r.get("valor"))
        if label in row:
            row[label] += value
            column_totals[label] = column_totals.get(label, 0.0) + value
        row["total"] += value

    ranked = sorted(by_item.values(), key=lambda r: -r["total"])
    shown = ranked[: max(1, int(limite or 20))]
    grand = round(sum(r["total"] for r in ranked), 2)

    # The TOTAL row covers every item, not only the ones listed, so the columns
    # reconcile with a monthly report asked for on its own. It is money only:
    # quantities are in each item's own stock unit, so a column adding litres
    # to pieces to boxes would be a number that means nothing.
    total_row = None
    if medida != "quantidade":
        total_row = {"item_code": "TOTAL", "item_name": "All items", "_style": "total",
                     "total": grand}
        for p in periods:
            total_row[p] = round(column_totals.get(p, 0.0), 2)
    for r in shown:
        r["total"] = round(r["total"], 2)
        for p in periods:
            r[p] = round(r.get(p, 0.0), 2)

    cell = number if medida == "quantidade" else currency
    columns = [text("item_code", "Code"), text("item_name", "Item")]
    columns += [cell(p, p) for p in periods]
    columns += [cell("total", "Total")]

    if medida == "quantidade":
        note = ("%d items sold in this period. The %d largest by quantity are listed, "
                "each in its own stock unit. There is no total row: quantities of "
                "different items are in different units, so adding them across items "
                "would mean nothing. Each item's own Total is valid, being one unit."
                % (len(ranked), len(shown)))
    else:
        note = ("%d items sold in this period, %s net in total. The %d largest are "
                "listed; the TOTAL row covers all of them, so its columns match a "
                "sales-by-period report for the same dates. These are line values, "
                "NET OF TAX." % (len(ranked), grand, len(shown)))
    if not complete:
        note += (" More item/date combinations matched than could be read, so this "
                 "cross-tab is incomplete - say so and narrow the dates.")
    if medida != "quantidade":
        note += _tax_bridge(filters, item_group, None, grand)

    return ToolResult(
        columns=columns,
        rows=shown + ([total_row] if total_row else []),
        source=describe("Sales Invoice Item (submitted invoices)", company,
                        from_date, to_date,
                        {"item group": item_group, "columns": agrupar_por,
                         "measure": medida or "valor"}),
        filters_applied=filters,
        note=note,
    )
