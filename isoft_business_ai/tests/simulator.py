"""A scripted stand-in for the model, so the whole pipeline can run with no API key.

It routes a Portuguese question to a tool using plain keyword rules, emits a
real ``tool_use`` block, reads the real result, and writes a short answer from
the real numbers.

What this DOES prove: the loop, argument validation, permission guards, tool
execution, conversation persistence, result rendering and cost accounting all
work end to end against live data.

What this does NOT prove: that a real model understands the question. Keyword
rules are a floor, not a forecast. The accuracy it reports is a baseline the
real model should beat, nothing more. Use ``--mode live`` for the real measure.
"""

import re

from frappe.utils import add_months, nowdate

MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}
LAST_DAY = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}


def _strip(text):
    return (text or "").lower()


def _year(text, default):
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return int(m.group(0)) if m else default


def resolve_dates(text, today=None):
    """Turn a Portuguese time expression into (from_date, to_date)."""
    today = today or nowdate()
    this_year = int(str(today)[:4])
    t = _strip(text)

    for name, num in MONTHS.items():
        if name in t:
            y = _year(t, this_year)
            last = 29 if (num == 2 and y % 4 == 0) else LAST_DAY[num]
            return "%04d-%02d-01" % (y, num), "%04d-%02d-%02d" % (y, num, last)

    if "primeiro trimestre" in t or "1o trimestre" in t or "first quarter" in t:
        y = _year(t, this_year)
        return "%d-01-01" % y, "%d-03-31" % y

    m = re.search(r"ultimos?\s+(\d+)\s+meses|last\s+(\d+)\s+months", t)
    if m:
        n = int(m.group(1) or m.group(2))
        return add_months(today, -n), today

    if "last month" in t or "mes passado" in t:
        first = "%s-01" % str(add_months(today, -1))[:7]
        return first, str(add_months(today, 0))[:7] + "-01"

    if "ano passado" in t or "last year" in t:
        return "%d-01-01" % (this_year - 1), "%d-12-31" % (this_year - 1)

    if ("este ano" in t or "ate hoje" in t or "deste ano" in t
            or "this year" in t or "year to date" in t):
        return "%d-01-01" % this_year, today

    if "de sempre" in t or "sempre" in t or "all time" in t or "ever" in t:
        return "%d-01-01" % (this_year - 1), "%d-12-31" % this_year

    y = _year(t, None)
    if y:
        return "%d-01-01" % y, "%d-12-31" % y

    return "%d-01-01" % this_year, today


def route(question, today=None):
    """Pick a tool and arguments. First match wins, so order matters."""
    t = _strip(question)
    frm, to = resolve_dates(question, today)

    def has(*words):
        return any(w in t for w in words)

    # --- lookups and context ------------------------------------------------
    if has("que empresas", "moeda da empresa", "desde quando", "que periodos",
                "what companies", "which companies", "company currency",
                "since when", "what periods", "what currency"):
        return "contexto_empresa", {}
    if has("procura", "find", "search", "look up") and has("fornecedor", "supplier"):
        return "procurar_fornecedor", {"termo": _term(question)}
    if has("procura", "algum cliente", "existe algum cliente", "find", "search", "look up"):
        if has("artigo", "produto", "tinta", "item", "product"):
            return "procurar_artigo", {"termo": _term(question)}
        if has("cliente", "customer"):
            return "procurar_cliente", {"termo": _term(question)}
    if has("procura", "find", "search") and has("artigo", "produto", "item", "product"):
        return "procurar_artigo", {"termo": _term(question)}
    # Guarded: an explicit stock/warehouse question is not a name lookup.
    if (has("que artigos temos com", "artigos com", "items with", "items named")
            and not has("stock", "armazem", "inventario", "warehouse", "inventory")):
        return "procurar_artigo", {"termo": _term(question)}

    # --- statement ----------------------------------------------------------
    if has("extrato", "conta corrente", "movimentos do cliente",
           "statement", "account ledger", "ledger for"):
        return "extrato_cliente", {"customer": _proper(question) or "", "from_date": frm, "to_date": to}

    # --- stock --------------------------------------------------------------
    if has("stock", "inventario", "armazem", "referencias",
           "inventory", "warehouse", "on hand"):
        if has("valor total", "total do", "quantas referencias", "valor do inventario",
               "total stock", "total value", "how many items", "inventory value",
               "total inventory"):
            return "stock_valor_total", {}
        m = re.search(r"artigo\s+([A-Z0-9]{3,})", question)
        if m:
            return "stock_actual", {"item_code": m.group(1)}
        if has("incluindo", "a zero", "including", "zero"):
            return "stock_actual", {"apenas_com_stock": False, "limite": 50}
        return "stock_actual", {"limite": 20}

    # --- payables -----------------------------------------------------------
    if has("devemos", "contas a pagar", "facturas de fornecedor",
           "do we owe", "we owe", "accounts payable", "payables",
           "supplier invoices"):
        if has("vencid", "overdue", "past due"):
            return "contas_a_pagar", {"apenas_vencido": True, "limite": 50}
        return "contas_a_pagar", {"limite": 50}

    # --- purchases ----------------------------------------------------------
    if has("compramos", "comprámos", "compras", "principais fornecedores",
           "nossos fornecedores", "did we buy", "purchases", "main suppliers",
           "top suppliers", "bought from"):
        if has("total de compras", "quanto compramos", "quanto comprámos",
               "total purchases", "how much did we buy"):
            return "compras_total", {"from_date": frm, "to_date": to, "por_fornecedor": False}
        return "compras_total", {"from_date": frm, "to_date": to, "limite": 20}

    # --- receivables --------------------------------------------------------
    if has("me deve", "deve dinheiro", "divida", "dívida", "a receber", "em atraso",
           "antiguidade", "aging", "nos deve", "owes us", "owe us", "who owes",
           "receivable", "outstanding", "overdue", "in arrears"):
        args = {"limite": 50}
        if has("vencid", "atraso", "90 dias", "overdue", "90 days", "arrears"):
            args["apenas_vencido"] = True
        if has("31 de dezembro", "a 31", "31 december", "end of 2025"):
            args["as_on"] = "2025-12-31"
        name = _proper(question)
        if name:
            args["customer"] = name
        return "contas_a_receber", args

    # --- invoices as documents ---------------------------------------------
    if has("factura", "invoice") and has("mostra", "quais factura", "lista", "ultimas",
                                     "por pagar", "vencidas", "show", "list",
                                     "which invoices", "unpaid", "latest"):
        args = {"from_date": frm, "to_date": to, "limite": 50}
        if has("por pagar", "unpaid"):
            args["estado"] = "Unpaid"
        elif has("vencidas", "overdue"):
            args["estado"] = "Overdue"
        return "facturas_de_venda", args

    # --- sales --------------------------------------------------------------
    if has("melhores clientes", "top", "ranking", "quem comprou", "melhor cliente",
           "best customers", "who bought", "biggest customers"):
        if has("artigo", "produto", "item", "product"):
            return "vendas_por_artigo", {"from_date": frm, "to_date": to, "limite": 10}
        limit = 10
        m = re.search(r"top\s+(\d+)", t)
        if m:
            limit = int(m.group(1))
        return "vendas_por_cliente", {"from_date": frm, "to_date": to, "limite": limit}

    if has("produtos", "artigos", "products", "items") and has("vend", "sell", "sold", "selling"):
        args = {"from_date": frm, "to_date": to, "limite": 20}
        if has("quantidade", "quantity", "by qty"):
            args["ordenar_por"] = "quantidade"
        return "vendas_por_artigo", args

    if has("evolucao", "evolução", "tendencia", "tendência", "mensal", "dia a dia",
           "por trimestre", "por ano", "compara", "trend", "monthly", "month by month",
           "day by day", "by quarter", "by year", "compare", "evolution"):
        group = "mes"
        if has("trimestre", "quarter"):
            group = "trimestre"
        elif has("por ano", "cada ano", "by year", "each year"):
            group = "ano"
        elif has("dia a dia", "diaria", "day by day", "daily"):
            group = "dia"
        return "vendas_por_periodo", {"from_date": frm, "to_date": to, "agrupar_por": group}

    if has("vend", "factur", "sell", "sold", "sales", "revenue", "invoiced"):
        args = {"from_date": frm, "to_date": to}
        if has("sem contar devolucoes", "sem devolucoes", "excluding returns",
                "without returns"):
            args["incluir_devolucoes"] = False
        return "vendas_total", args

    return "contexto_empresa", {}


def _term(question):
    """Pull the search term out of a lookup question."""
    m = re.search(r"(?:procura(?:r)?(?:\s+o|\s+a)?\s+(?:cliente|artigo|artigos|fornecedor|produto)?\s*)([\w\-]+)",
                  question, re.I)
    if m and m.group(1).lower() not in ("o", "a", "os", "as"):
        return m.group(1)
    caps = re.findall(r"\b([A-Z][A-Z0-9]{2,})\b", question)
    if caps:
        return caps[0]
    m = re.search(r"com\s+(\w+)\s+no\s+nome", question, re.I)
    if m:
        return m.group(1)
    return question.split()[-1].strip("?")


def _proper(question):
    """Best-effort customer code: an ALL-CAPS run of two or more words."""
    m = re.search(r"\b([A-Z][A-Z]+(?:\s+[A-Z]+)+)\b", question)
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------
# A stand-in for AnthropicClient with the same create() signature.
# --------------------------------------------------------------------------

class _Block(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None}


class _Usage(object):
    """Token counts estimated from real payload sizes, so the cost report
    produces a realistic shape rather than zeros."""

    def __init__(self, system, messages, tools, output_chars):
        import json as _json

        prefix = len(_json.dumps(tools, default=str)) + len(
            "".join(b.get("text", "") for b in system))
        convo = len(_json.dumps(messages, default=str))
        self.cache_read_input_tokens = int(prefix / 3.5)
        self.cache_creation_input_tokens = 0
        self.input_tokens = int(convo / 3.5)
        self.output_tokens = int(output_chars / 3.5)


class _Response(object):
    def __init__(self, content, stop_reason, usage):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = usage
        self.model = "simulado (sem chamada a API)"


class SimulatedClient(object):
    """Routes by keyword, executes real tools through the real loop, then
    writes an answer from the numbers that actually came back."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.calls = 0
        self.retried = False

    def create(self, system, messages, tools):
        import json as _json

        self.calls += 1
        question = self._question(messages)
        last_result = self._last_result(messages)

        # First turn: choose a tool.
        if last_result is None:
            name, args = route(question)
            block = _Block(type="tool_use", id="sim%d" % self.calls, name=name, input=args)
            return _Response([block], "tool_use",
                             _Usage(system, messages, tools, len(_json.dumps(args))))

        # Empty result and a name in the question: try resolving the name once.
        # This is the self-correction path the real model is meant to take.
        if (not last_result.get("rows")) and not self.retried and _proper(question):
            self.retried = True
            block = _Block(type="tool_use", id="sim%d" % self.calls,
                           name="procurar_cliente", input={"termo": _proper(question)})
            return _Response([block], "tool_use", _Usage(system, messages, tools, 40))

        text = self._answer(question, last_result)
        return _Response([_Block(type="text", text=text)], "end_turn",
                         _Usage(system, messages, tools, len(text)))

    # -- helpers ---------------------------------------------------------
    def _question(self, messages):
        for m in messages:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                return m["content"]
        return ""

    def _last_result(self, messages):
        import json as _json

        for m in reversed(messages):
            if m.get("role") != "user" or not isinstance(m.get("content"), list):
                continue
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    if b.get("is_error"):
                        return {"rows": [], "error": b.get("content")}
                    try:
                        return _json.loads(b.get("content") or "{}")
                    except ValueError:
                        return {"rows": []}
        return None

    def _answer(self, question, result):
        """Compose an answer strictly from what the tool returned."""
        if result.get("error"):
            return "Nao consegui obter esses dados: %s" % str(result["error"])[:200]

        rows = result.get("rows") or []
        cols = result.get("columns") or []
        if not rows:
            return ("Nao encontrei dados para essa pergunta. Fonte consultada: %s. "
                    "Verifique o periodo ou o nome indicado." % result.get("source", "-"))

        parts = []
        first = rows[0]
        for i, key in enumerate(cols[:3]):
            if i < len(first):
                parts.append("%s: %s" % (key, first[i]))

        answer = "%s. (%d linha%s)" % (
            ", ".join(parts), result.get("row_count", len(rows)),
            "s" if result.get("row_count", len(rows)) != 1 else "")
        if result.get("note"):
            answer += " %s" % result["note"]
        answer += "\nFonte: %s" % result.get("source", "-")
        return answer
