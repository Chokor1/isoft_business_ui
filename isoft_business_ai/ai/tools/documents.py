"""Tools for working with one named document.

Generic on purpose: ERPNext has 274 business DocTypes on this site and a tool
per type would be unmaintainable and would flood the context. One tool reads
any of them, with the DocType's own metadata deciding what is worth showing.
"""

from isoft_business_ai.ai import documents
from isoft_business_ai.ai.formatting import text
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool


@ai_tool(
    name="read_document",
    description=(
        "Open one named business document and read its header fields, its lines, and "
        "any pictures or files attached to it — a quotation, order, invoice, delivery "
        "note, stock entry, payment, an item, a customer and so on. This is also how you "
        "show a product photo that is stored in the ERP: call it and the picture is "
        "displayed with your answer. "
        "Use when the user mentions a specific document, or refers to 'this quotation' "
        "or 'the open invoice'. The document the user is viewing is supplied to you "
        "automatically when they mention it."
    ),
    params={
        "doctype": Param.text("DocType, for example 'Quotation' or 'Sales Invoice'."),
        "name": Param.text("The document's exact name/id."),
        "linhas": Param.integer("How many lines to return. Default 12.", optional=True),
    },
    doctypes=[],
    group="documentos",
)
def read_document(doctype, name, linhas=12):
    summary = documents.summarise(doctype, name, child_rows=int(linhas or 12))

    lines = summary.get("lines") or {}
    cols = lines.get("columns") or []
    rows = [dict(zip(cols, r)) for r in (lines.get("rows") or [])]

    return ToolResult(
        links=[{"label": "Open %s %s" % (doctype, summary["name"]),
                "doctype": doctype, "name": summary["name"]}],
        columns=[text(c, c.replace("_", " ").title()) for c in cols],
        rows=rows,
        source=("%s %s (%s)" % (doctype, summary["name"], summary["docstatus"])
                if summary.get("docstatus") else "%s %s" % (doctype, summary["name"])),
        filters_applied={"doctype": doctype, "name": name},
        header=summary.get("fields"),
        media=summary.get("media"),
        note=lines.get("note"),
    )


@ai_tool(
    name="find_document",
    description=(
        "Search for a business document by part of its name or id across the common "
        "selling, buying and stock document types. Use when the user names a document "
        "loosely and you need its exact id before calling read_document."
    ),
    params={
        "termo": Param.text("Part of the document id."),
        "doctype": Param.text("Restrict to one DocType.", optional=True),
    },
    doctypes=[],
    group="documentos",
)
def find_document(termo, doctype=None):
    hits = documents.search(termo, doctype=doctype, limit=10)
    return ToolResult(
        links=[{"label": "%s %s" % (h["doctype"], h["name"]),
                "doctype": h["doctype"], "name": h["name"]} for h in hits[:6]],
        columns=[text("doctype", "Type"), text("name", "Document"), text("label", "Title")],
        rows=hits,
        source="document search for '%s'" % termo,
        note="Use the Type and Document values as read_document's parameters.",
    )
