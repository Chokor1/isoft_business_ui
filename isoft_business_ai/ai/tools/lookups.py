"""Lookup tools.

These exist so the assistant can recover on its own. A user asks about a
customer by the name they remember; the sales tools need the exact code. Rather than guessing
and returning an empty result, the model calls a lookup first, or calls one
after an empty result and tries again. This is most of what makes the
conversation feel like it understands the business.
"""

import frappe
from frappe.utils import nowdate

from isoft_business_ai.ai.formatting import text
from isoft_business_ai.ai.query import fetch
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool
from isoft_business_ai.ai.security import allowed_companies, resolve_company


@ai_tool(
    name="procurar_cliente",
    description=(
        "Search customers by part of the name or code. ALWAYS use this before filtering by "
        "customer when the user writes a name rather than an exact code. "
        "'find customer', 'procurar cliente'."
    ),
    params={
        "termo": Param.text("Part of the customer name or code."),
        "limite": Param.integer("Maximum results. Default 15.", optional=True),
    },
    doctypes=["Customer"],
    group="pesquisa",
)
def procurar_cliente(termo, limite=15):
    like = "%" + (termo or "").strip() + "%"
    rows = fetch(
        "Customer",
        fields=["name", "customer_name", "customer_group", "territory", "disabled"],
        or_filters=[["customer_name", "like", like], ["name", "like", like]],
        order_by="customer_name asc",
        limit=limite or 15,
    )
    return ToolResult(
        columns=[
            text("name", "Code"),
            text("customer_name", "Name"),
            text("customer_group", "Group"),
            text("territory", "Territory"),
        ],
        rows=rows,
        source="Customer | search for '%s'" % termo,
        note="Use the value in the Code column as the 'customer' parameter in other tools.",
    )


@ai_tool(
    name="procurar_fornecedor",
    description=(
        "Search suppliers by part of the name or code. Use before filtering by supplier "
        "when the user writes a name rather than a code."
    ),
    params={
        "termo": Param.text("Part of the supplier name or code."),
        "limite": Param.integer("Maximum results. Default 15.", optional=True),
    },
    doctypes=["Supplier"],
    group="pesquisa",
)
def procurar_fornecedor(termo, limite=15):
    like = "%" + (termo or "").strip() + "%"
    rows = fetch(
        "Supplier",
        fields=["name", "supplier_name", "supplier_group"],
        or_filters=[["supplier_name", "like", like], ["name", "like", like]],
        order_by="supplier_name asc",
        limit=limite or 15,
    )
    return ToolResult(
        columns=[text("name", "Code"), text("supplier_name", "Name"), text("supplier_group", "Group")],
        rows=rows,
        source="Supplier | search for '%s'" % termo,
        note="Use the value in the Code column as the 'supplier' parameter.",
    )


@ai_tool(
    name="procurar_artigo",
    description=(
        "Search items by part of the name or code. Use before filtering by item when the "
        "user describes the product in words. 'find item', 'procurar artigo'."
    ),
    params={
        "termo": Param.text("Part of the item name or code."),
        "limite": Param.integer("Maximum results. Default 15.", optional=True),
    },
    doctypes=["Item"],
    group="pesquisa",
)
def procurar_artigo(termo, limite=15):
    like = "%" + (termo or "").strip() + "%"
    rows = fetch(
        "Item",
        fields=["name", "item_name", "item_group", "stock_uom", "disabled"],
        or_filters=[["item_name", "like", like], ["name", "like", like]],
        order_by="item_name asc",
        limit=limite or 15,
    )
    return ToolResult(
        columns=[
            text("name", "Code"),
            text("item_name", "Item"),
            text("item_group", "Group"),
            text("stock_uom", "Unit"),
        ],
        rows=rows,
        source="Item | search for '%s'" % termo,
        note="Use the value in the Code column as the 'item_code' parameter.",
    )


@ai_tool(
    name="contexto_empresa",
    description=(
        "Basic context: companies the user may access, default company, currency, today's "
        "date and the range of dates for which data exists. Call when unsure which company "
        "to use or what periods are available."
    ),
    params={},
    doctypes=["Company"],
    group="pesquisa",
)
def contexto_empresa():
    companies = allowed_companies()
    default = resolve_company()
    currency = frappe.db.get_value("Company", default, "default_currency")

    span = fetch(
        "Sales Invoice",
        fields=["min(posting_date) as primeira", "max(posting_date) as ultima"],
        filters={"docstatus": 1, "company": default},
    )
    span = span[0] if span else {}

    row = {
        "hoje": nowdate(),
        "empresa_por_omissao": default,
        "moeda": currency,
        "empresas_disponiveis": ", ".join(companies),
        "primeira_factura": span.get("primeira"),
        "ultima_factura": span.get("ultima"),
    }
    return ToolResult(
        columns=[
            text("hoje", "Today"),
            text("empresa_por_omissao", "Default company"),
            text("moeda", "Currency"),
            text("empresas_disponiveis", "Available companies"),
            text("primeira_factura", "First invoice"),
            text("ultima_factura", "Last invoice"),
        ],
        rows=[row],
        source="Company / Sales Invoice",
    )


@ai_tool(
    name="procurar_armazem",
    description=(
        "Search warehouses, shops and stores by part of the name. ALWAYS use this before "
        "filtering stock by warehouse when the user names a shop in words - 'the Alvalade "
        "shop', 'loja do Alvalade', 'main store'. Returns the exact warehouse name the "
        "stock tools need."
    ),
    params={
        "termo": Param.text("Part of the warehouse name.", optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Warehouse"],
    group="pesquisa",
)
def procurar_armazem(termo=None, company=None):
    company = resolve_company(company)
    filters = {"company": company, "is_group": 0}
    or_filters = None
    if (termo or "").strip():
        like = "%" + termo.strip() + "%"
        or_filters = [["name", "like", like], ["warehouse_name", "like", like]]
    rows = fetch(
        "Warehouse",
        fields=["name", "warehouse_name", "disabled"],
        filters=filters,
        or_filters=or_filters,
        order_by="name asc",
        limit=50,
    )
    note = ("%d warehouse(s) match. Pass the Code column to the stock tools, exactly as "
            "shown." % len(rows))
    if not rows and (termo or "").strip():
        note = ("No warehouse in %s matches '%s'. Call this tool with no search term to "
                "see every warehouse before telling the user it does not exist."
                % (company, termo))
    return ToolResult(
        columns=[text("name", "Code"), text("warehouse_name", "Name"),
                 text("disabled", "Disabled")],
        rows=rows,
        source="Warehouse in %s" % company,
        filters_applied={"company": company, "termo": termo},
        note=note,
    )


@ai_tool(
    name="procurar_conta",
    description=(
        "Search the chart of accounts by part of the name or number. ALWAYS use this before "
        "passing an account to general_ledger or any other tool when you only know what the "
        "account is called. Account names here carry their PGC number and the company "
        "suffix - 'Stock Adjustment' is really '78041 - Stock Adjustment - ACME', and the "
        "short form matches nothing."
    ),
    params={
        "termo": Param.text("Part of the account name or number."),
        "apenas_movimento": Param.boolean(
            "If true, only accounts that can be posted to (not group accounts).",
            optional=True),
        "company": Param.text("Company.", optional=True),
    },
    doctypes=["Account"],
    group="pesquisa",
)
def procurar_conta(termo, apenas_movimento=True, company=None):
    company = resolve_company(company)
    like = "%" + (termo or "").strip() + "%"
    filters = {"company": company}
    if apenas_movimento:
        filters["is_group"] = 0
    rows = fetch(
        "Account",
        fields=["name", "account_number", "account_name", "root_type", "account_type",
                "is_group"],
        filters=filters,
        or_filters=[["name", "like", like], ["account_name", "like", like],
                    ["account_number", "like", like]],
        order_by="account_number asc",
        limit=30,
    )
    note = ("%d account(s) match. Pass the Code column verbatim - it is the full name "
            "including the number and the company suffix." % len(rows))
    if not rows:
        note = ("No account in %s matches '%s'. Try a shorter term or the PGC number; do "
                "not guess the full name." % (company, termo))
    return ToolResult(
        columns=[text("name", "Code"), text("account_name", "Name"),
                 text("root_type", "Type"), text("account_type", "Account type")],
        rows=rows,
        source="Account in %s" % company,
        filters_applied={"company": company, "termo": termo},
        note=note,
    )
