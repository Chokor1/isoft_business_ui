"""Whitelisted endpoints for the chat page."""

import json

import frappe
from frappe import _

from isoft_business_ai.ai import loop
from isoft_business_ai.ai.client import check_connection
from isoft_business_ai.ai.registry import load_tools, tool_schemas

# How many transcript entries to replay. Tool results are verbose, so a long
# conversation is trimmed from the front rather than resent in full.
HISTORY_LIMIT = 30

# Same bracketed form the widget inserts; see ai/loop.py.

ROLE = "Business AI User"


def _check_access():
    """Who may use the assistant at all.

    The role is the gate, deliberately. Granting System Manager by itself used
    to be enough, which meant 12 people here could reach the assistant while
    exactly one had been given the role - so the role decided nothing.
    Administrator stays a safety hatch so the app cannot lock out the person
    who has to fix it.
    """
    if frappe.session.user == "Administrator":
        return
    if ROLE not in frappe.get_roles():
        frappe.throw(
            _("You need the {0} role to use the business assistant. "
              "An administrator can grant it from your User record.").format(ROLE),
            frappe.PermissionError,
        )


def _trim(messages):
    """Trim history, never starting the replay on a tool_result message.

    A ``tool_result`` whose matching ``tool_use`` was trimmed away is rejected
    by the API, so the window is moved forward until it starts cleanly.
    """
    if len(messages) <= HISTORY_LIMIT:
        return messages

    window = messages[-HISTORY_LIMIT:]
    while window:
        first = window[0]
        content = first.get("content")
        starts_on_tool_result = (
            first.get("role") == "user"
            and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        )
        if not starts_on_tool_result:
            break
        window = window[1:]
    return window


@frappe.whitelist()
def ask(question, conversation=None):
    """Answer one question, persisting the turn to a conversation."""
    _check_access()
    question = (question or "").strip()
    if not question:
        frappe.throw(_("Please type a question."))
    if len(question) > 4000:
        frappe.throw(_("Question is too long."))

    # Before the conversation is touched and before the model is called, so a
    # user who is over their cap neither spends anything nor leaves a stub.
    from isoft_business_ai.ai import usage as usage_engine
    usage_engine.check_limits()

    convo = _get_or_create_conversation(conversation, question)

    history = []
    if convo.history_json:
        try:
            history = _trim(json.loads(convo.history_json))
        except ValueError:
            history = []

    result = loop.ask(question, history=history, company=convo.company,
                      provider_name=convo.get('provider'))

    frappe.get_doc({
        "doctype": "Isoft AI Message",
        "conversation": convo.name,
        "role": "user",
        "content": question,
    }).insert(ignore_permissions=True)

    message = frappe.get_doc({
        "doctype": "Isoft AI Message",
        "conversation": convo.name,
        "role": "assistant",
        "content": result["answer"],
        "results_json": json.dumps(result["results"], default=str, ensure_ascii=False),
        "usage_json": json.dumps(result["usage"]),
        "model": result.get("model"),
    })
    message.insert(ignore_permissions=True)

    convo.db_set(
        "history_json",
        json.dumps(_trim(result["messages"]), default=str, ensure_ascii=False),
        update_modified=True,
    )
    convo.db_set("provider", result.get("provider"), update_modified=False)
    frappe.db.commit()

    return {
        "conversation": convo.name,
        "title": convo.title,
        "message": message.name,
        "answer": result["answer"],
        "results": result["results"],
        "usage": result["usage"],
    }


def _get_or_create_conversation(name, first_question):
    if name:
        convo = frappe.get_doc("Isoft AI Conversation", name)
        if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
            frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)
        return convo

    # The mention markup is for the model, not for a list of conversations:
    # "@[Quotation:FP 2026/18] …" would read as an unrendered tag.
    readable = loop.MENTION_RE.sub(lambda m: "%s %s" % (m.group(1), m.group(2)),
                              first_question or "")
    title = readable.strip().split("\n")[0][:80]
    convo = frappe.get_doc({
        "doctype": "Isoft AI Conversation",
        "title": title or _("New conversation"),
    })
    convo.insert(ignore_permissions=True)
    return convo


@frappe.whitelist()
def list_conversations(limit=30, search=None):
    """Own conversations, newest first, optionally filtered by title.

    Search is a title match rather than a full-text search of the messages:
    the data layer indexes titles, and promising more than that in the UI
    would be a lie.
    """
    _check_access()
    filters = {"owner": frappe.session.user, "soft_delete": 0}
    search = (search or "").strip()
    if search:
        filters["title"] = ["like", "%" + search + "%"]
    return frappe.get_all(
        "Isoft AI Conversation",
        filters=filters,
        fields=["name", "title", "modified"],
        order_by="modified desc",
        limit_page_length=int(limit),
    )


@frappe.whitelist()
def rename_conversation(name, title):
    """Rename one's own conversation."""
    _check_access()
    title = (title or "").strip()
    if not title:
        frappe.throw(_("A conversation needs a title."))
    if len(title) > 140:
        title = title[:140]

    convo = frappe.get_doc("Isoft AI Conversation", name)
    if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)
    convo.db_set("title", title)
    frappe.db.commit()
    return {"ok": True, "title": title}


@frappe.whitelist()
def get_conversation(name):
    _check_access()
    convo = frappe.get_doc("Isoft AI Conversation", name)
    if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)

    messages = frappe.get_all(
        "Isoft AI Message",
        filters={"conversation": name},
        fields=["name", "role", "content", "results_json", "creation"],
        order_by="creation asc",
        limit_page_length=0,
    )
    for m in messages:
        try:
            m["results"] = json.loads(m.pop("results_json") or "[]")
        except ValueError:
            m["results"] = []
        m.pop("results_json", None)

    return {"name": convo.name, "title": convo.title, "messages": messages}


@frappe.whitelist()
def delete_conversation(name):
    _check_access()
    convo = frappe.get_doc("Isoft AI Conversation", name)
    if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)
    convo.db_set("soft_delete", 1)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def search_documents(query=None, doctype=None, limit=10):
    """Autocomplete for the chat's @ mentions. Permission-filtered."""
    _check_access()
    from isoft_business_ai.ai import documents

    return documents.search(query, doctype=doctype or None, limit=int(limit))


@frappe.whitelist()
def describe_document(doctype, name):
    """Header summary for the chip the widget shows for the open document."""
    _check_access()
    from isoft_business_ai.ai import documents

    if not documents.is_business_doctype(doctype):
        return {"ok": False}
    if not frappe.has_permission(doctype, "read", doc=name):
        return {"ok": False}
    meta = frappe.get_meta(doctype)
    title = None
    if meta.title_field:
        title = frappe.db.get_value(doctype, name, meta.title_field)
    return {"ok": True, "doctype": doctype, "name": name,
            "title": title if title and title != name else ""}


@frappe.whitelist()
def briefing(company=None):
    """Where the manager stands, for the chat's opening screen.

    Deliberately runs no model: it is the same permission-aware queries the
    tools use, rendered client-side. Opening the chat therefore costs nothing
    and is instant, and the figures are identical to what the assistant would
    quote if asked.
    """
    _check_access()
    from isoft_business_ai.ai import alerts as alerts_engine
    from isoft_business_ai.ai import targets as targets_engine
    from isoft_business_ai.ai.security import resolve_company

    try:
        company = resolve_company(company)
    except Exception:
        return {"ok": False}

    out = {"ok": True, "company": company, "targets": [], "alerts": [],
           "suggestions": []}
    try:
        # Carried here rather than fetched separately: the opening screen and
        # the composer typeahead both want it, and both are already waiting on
        # this call.
        from isoft_business_ai.ai import suggestions as catalogue
        out["suggestions"] = catalogue.available()
    except Exception:
        pass
    try:
        out["targets"] = [targets_engine.progress(t)
                          for t in targets_engine.active_targets(company)]
    except Exception:
        pass
    try:
        # Target alerts are dropped here: the briefing already shows each
        # target as its own card, so repeating it reads as noise.
        out["alerts"] = [a for a in alerts_engine.run(company)
                         if a.get("kind") != "target"][:4]
    except Exception:
        pass
    return out


@frappe.whitelist()
def flag_answer(message, verdict, comment=None):
    """Record that an answer was wrong, with the evidence to investigate it.

    Stores only. A report never changes a tool, a glossary definition or a
    prompt: one user's view must not silently alter what everyone else is told.
    What it does give an investigator is the exact question, the answer, and the
    tools that ran with their parameters - which is what a gold-set case is made
    from.
    """
    _check_access()

    msg = frappe.get_doc("Isoft AI Message", message)
    convo = frappe.get_doc("Isoft AI Conversation", msg.conversation)
    if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)
    if msg.role != "assistant":
        frappe.throw(_("Only an answer can be reported."))

    # The question is the user turn immediately before this answer.
    asked = frappe.get_all(
        "Isoft AI Message",
        filters={"conversation": msg.conversation, "role": "user",
                 "creation": ["<", msg.creation]},
        fields=["content"], order_by="creation desc", limit_page_length=1,
    )

    # Keep the tool calls and their parameters, not the result rows: the rows
    # are reproducible from the parameters and would bloat the record.
    tools = []
    try:
        for r in json.loads(msg.results_json or "[]"):
            # The payload calls them "arguments"; they are the whole point of
            # the record, since a confirmed fault is reproduced from them.
            tools.append({"tool": r.get("tool"),
                          "arguments": r.get("arguments"),
                          "rows": r.get("row_count"),
                          "truncated": r.get("truncated"),
                          "elapsed_ms": r.get("elapsed_ms"),
                          "source": r.get("source")})
    except ValueError:
        pass

    doc = frappe.get_doc({
        "doctype": "Isoft AI Feedback",
        "verdict": verdict,
        "status": "New",
        "conversation": msg.conversation,
        "message": msg.name,
        "question": (asked[0]["content"] if asked else "")[:500],
        "answer": msg.content,
        "comment": comment,
        "company": _safe_company(),
        "model": _message_model(msg),
        "reported_on": frappe.utils.now(),
        "tools_json": json.dumps(tools, default=str, ensure_ascii=False, indent=1),
    })
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "name": doc.name}


def _safe_company():
    try:
        from isoft_business_ai.ai.security import resolve_company
        return resolve_company()
    except Exception:
        return None


def _message_model(msg):
    try:
        return (json.loads(msg.usage_json or "{}") or {}).get("model")
    except ValueError:
        return None


@frappe.whitelist()
def suggestions():
    """Questions to offer, for the opening screen and the composer typeahead.

    Returned whole and filtered once, not per keystroke: it is two dozen short
    strings, so the client can match against it instantly and offline.
    """
    _check_access()
    from isoft_business_ai.ai import suggestions as catalogue

    return catalogue.available()


def _assert_manager():
    """The usage console is an administrator's view of everyone's spend.

    Deliberately NOT _check_access(): auditing what the assistant costs is a
    management job, and whoever does it need not be a user of the assistant.
    Chaining the two meant a System Manager had to be granted the app role
    before they could see the bill.
    """
    if frappe.session.user == "Administrator":
        return
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only a System Manager can see assistant usage."),
                     frappe.PermissionError)


@frappe.whitelist()
def usage_overview(from_date=None, to_date=None, user=None):
    """Spend and tokens for a window, cut by day, user, model and conversation."""
    _assert_manager()
    from isoft_business_ai.ai import usage as engine

    to_date = to_date or frappe.utils.nowdate()
    from_date = from_date or frappe.utils.add_days(to_date, -29)
    data = engine.overview(from_date, to_date, user=user or None)
    data["by_tool"] = engine.by_tool(from_date, to_date)

    s = frappe.get_single("Isoft Business AI Settings")
    data["limits"] = {
        "daily_question_limit": int(frappe.utils.flt(s.get("daily_question_limit"))),
        "daily_token_limit": int(frappe.utils.flt(s.get("daily_token_limit"))),
        "monthly_budget_usd": frappe.utils.flt(s.get("monthly_budget_usd")),
        "enabled": int(frappe.utils.cint(s.get("enabled"))),
        "model": s.get("model"),
        "provider": s.get("provider"),
        "max_iterations": int(frappe.utils.flt(s.get("max_iterations"))),
    }
    data["month"] = engine.spent_this_month()
    return data


@frappe.whitelist()
def usage_conversation(name):
    """One conversation's turns with the tokens and cost of each answer."""
    _assert_manager()
    from isoft_business_ai.ai import usage as engine

    convo = frappe.get_doc("Isoft AI Conversation", name)
    messages = frappe.get_all(
        "Isoft AI Message", filters={"conversation": name},
        fields=["name", "role", "content", "creation", "usage_json", "model",
                "results_json"],
        order_by="creation asc", limit_page_length=0)

    fallback = frappe.db.get_single_value("Isoft Business AI Settings", "model")
    out = []
    for m in messages:
        row = {"name": m["name"], "role": m["role"], "content": m["content"],
               "creation": str(m["creation"]), "tools": []}
        try:
            row["tools"] = [{"tool": r.get("tool"), "rows": r.get("row_count"),
                             "ms": r.get("elapsed_ms")}
                            for r in json.loads(m["results_json"] or "[]")]
        except ValueError:
            pass
        if m["role"] == "assistant":
            try:
                u = json.loads(m["usage_json"] or "{}")
            except ValueError:
                u = {}
            model = m.get("model") or fallback
            cost, priced = engine.cost_of(u, model)
            row.update({
                "model": model, "priced": priced,
                "fresh": int(frappe.utils.flt(u.get("input_tokens"))),
                "cached": int(frappe.utils.flt(u.get("cache_read_input_tokens"))),
                "output": int(frappe.utils.flt(u.get("output_tokens"))),
                "cost": round(cost, 5),
            })
        out.append(row)

    return {"name": convo.name, "title": convo.title, "owner": convo.owner,
            "company": convo.company, "messages": out}


@frappe.whitelist()
def save_limits(daily_question_limit=0, daily_token_limit=0, monthly_budget_usd=0,
                enabled=None):
    """Write the caps back. Nothing else on Settings is touched from here."""
    _assert_manager()
    s = frappe.get_single("Isoft Business AI Settings")
    s.daily_question_limit = max(0, int(frappe.utils.flt(daily_question_limit)))
    s.daily_token_limit = max(0, int(frappe.utils.flt(daily_token_limit)))
    s.monthly_budget_usd = max(0.0, frappe.utils.flt(monthly_budget_usd))
    if enabled is not None:
        s.enabled = 1 if frappe.utils.cint(enabled) else 0
    s.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def list_tools():
    """Catalogue of what the assistant can answer, for the UI help panel."""
    _check_access()
    load_tools()
    from isoft_business_ai.ai.registry import TOOL_REGISTRY

    out = []
    for name in sorted(TOOL_REGISTRY):
        tool = TOOL_REGISTRY[name]
        out.append({
            "name": name,
            "group": tool["group"],
            "description": tool["description"],
            "doctypes": tool["doctypes"],
        })
    return out


@frappe.whitelist()
def export_result(message, index=0):
    """Export one result table of one answer to xlsx."""
    _check_access()
    from frappe.utils.xlsxutils import make_xlsx

    doc = frappe.get_doc("Isoft AI Message", message)
    convo = frappe.get_doc("Isoft AI Conversation", doc.conversation)
    if convo.owner != frappe.session.user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("This conversation does not belong to you."), frappe.PermissionError)

    results = json.loads(doc.results_json or "[]")
    index = int(index)
    if index >= len(results):
        frappe.throw(_("Result not found."))

    result = results[index]
    columns = result.get("columns") or []
    data = [[c["label"] for c in columns]]
    for row in result.get("rows") or []:
        data.append([row.get(c["key"]) for c in columns])

    xlsx = make_xlsx(data, "Resultado")
    frappe.response["filename"] = "%s.xlsx" % (result.get("tool") or "resultado")
    frappe.response["filecontent"] = xlsx.getvalue()
    frappe.response["type"] = "binary"


@frappe.whitelist()
def readiness():
    """Everything that has to be true before a question can be answered.

    Written because a missing provider SDK first showed up as a bare
    ModuleNotFoundError on a production migrate, and there was no way to ask
    the app what it was missing.
    """
    _check_access()
    import importlib

    settings = frappe.get_single("Isoft Business AI Settings")
    provider = (settings.get("provider") or "openai").strip().lower()
    module = {"openai": "openai", "anthropic": "anthropic"}.get(provider, provider)
    conf_key = "openai_api_key" if provider == "openai" else "anthropic_api_key"

    try:
        importlib.import_module(module)
        sdk = True
        sdk_detail = getattr(importlib.import_module(module), "__version__", "installed")
    except ImportError:
        sdk = False
        sdk_detail = ("not installed - run: ./env/bin/pip install -r "
                      "apps/isoft_business_ai/requirements.txt && bench restart")

    checks = [
        {"check": "Assistant enabled", "ok": bool(settings.get("enabled")),
         "detail": "Isoft Business AI Settings"},
        {"check": "Provider SDK (%s)" % module, "ok": sdk, "detail": str(sdk_detail)},
        {"check": "API key in site_config", "ok": bool(frappe.conf.get(conf_key)),
         "detail": "key: %s" % conf_key},
        {"check": "Model configured", "ok": bool(settings.get("model")),
         "detail": settings.get("model") or "none"},
        {"check": "You hold the %s role" % ROLE,
         "ok": ROLE in frappe.get_roles() or frappe.session.user == "Administrator",
         "detail": "or Administrator"},
    ]
    return {"ready": all(c["ok"] for c in checks), "provider": provider,
            "checks": checks}


@frappe.whitelist()
def test_connection():
    """Settings button. Restricted to System Manager: it spends money."""
    if "System Manager" not in frappe.get_roles():
        frappe.throw(_("Only a System Manager can test the connection."), frappe.PermissionError)
    try:
        result = check_connection()
        status = "OK - model %s, %s input tokens." % (
            result["model"], result["input_tokens"])
    except Exception as e:
        status = "FAILED - %s: %s" % (type(e).__name__, str(e)[:300])
        result = {"ok": False, "error": status}

    frappe.db.set_value("Isoft Business AI Settings", None, "connection_status", status)
    frappe.db.commit()
    return result
