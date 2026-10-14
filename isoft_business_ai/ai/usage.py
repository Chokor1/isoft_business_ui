# -*- coding: utf-8 -*-
"""What the assistant has actually cost, and who spent it.

Every answer already stores its own token usage on the Isoft AI Message record,
including the cached portion, so none of this is estimated. The one thing the
older records cannot tell us is which model produced them - that is stored from
now on, and anything before carries the configured model with a note saying so.

Costing deliberately counts all three token streams. Reading `input_tokens`
alone understates the bill by whatever the cache served, which on this install
is about 89 per cent of input.
"""

from __future__ import unicode_literals

import json

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

from isoft_business_ai.cost import PRICING


def _price(model):
    """Per-million prices for a model, falling back to something sane."""
    if model and model in PRICING:
        return PRICING[model]
    # An unknown model must not silently cost zero.
    return None


def cost_of(usage, model):
    """USD for one answer. Returns (cost, priced) so an unpriced model shows."""
    p = _price(model)
    if not p:
        return 0.0, False
    fresh = flt(usage.get("input_tokens"))
    cached = flt(usage.get("cache_read_input_tokens"))
    written = flt(usage.get("cache_creation_input_tokens"))
    out = flt(usage.get("output_tokens"))
    total = (fresh * p["input"] + cached * p["cached"]
             + written * p.get("cache_write", p["input"]) + out * p["output"])
    return total / 1000000.0, True


def _default_model():
    try:
        return frappe.db.get_single_value("Isoft Business AI Settings", "model")
    except Exception:
        return None


def _rows(from_date, to_date, user=None, conversation=None):
    """Assistant turns in the window, with their usage parsed."""
    filters = {"role": "assistant"}
    if conversation:
        filters["conversation"] = conversation
    messages = frappe.get_all(
        "Isoft AI Message",
        filters=filters,
        fields=["name", "conversation", "owner", "creation", "usage_json", "model"],
        order_by="creation asc",
        limit_page_length=0,
    )
    fallback = _default_model()
    start, end = getdate(from_date), getdate(to_date)
    out = []
    for m in messages:
        day = getdate(m["creation"])
        if day < start or day > end:
            continue
        if user and m["owner"] != user:
            continue
        try:
            usage = json.loads(m["usage_json"] or "{}")
        except ValueError:
            usage = {}
        model = m.get("model") or fallback
        cost, priced = cost_of(usage, model)
        out.append({
            "message": m["name"],
            "conversation": m["conversation"],
            "user": m["owner"],
            "when": m["creation"],
            "day": str(day),
            "model": model,
            "priced": priced,
            "fresh": int(flt(usage.get("input_tokens"))),
            "cached": int(flt(usage.get("cache_read_input_tokens"))),
            "written": int(flt(usage.get("cache_creation_input_tokens"))),
            "output": int(flt(usage.get("output_tokens"))),
            "cost": cost,
        })
    return out


def _blank():
    return {"questions": 0, "fresh": 0, "cached": 0, "written": 0, "output": 0,
            "cost": 0.0, "unpriced": 0}


def _add(bucket, r):
    bucket["questions"] += 1
    for k in ("fresh", "cached", "written", "output"):
        bucket[k] += r[k]
    bucket["cost"] += r["cost"]
    if not r["priced"]:
        bucket["unpriced"] += 1
    return bucket


def _finish(bucket):
    bucket["cost"] = round(bucket["cost"], 4)
    bucket["input_total"] = bucket["fresh"] + bucket["cached"] + bucket["written"]
    bucket["tokens"] = bucket["input_total"] + bucket["output"]
    bucket["cache_pct"] = (round(bucket["cached"] * 100.0 / bucket["input_total"], 1)
                           if bucket["input_total"] else None)
    bucket["cost_per_question"] = (round(bucket["cost"] / bucket["questions"], 4)
                                   if bucket["questions"] else 0.0)
    return bucket


def overview(from_date, to_date, user=None):
    """Totals, plus the same cut by day, by user, by model and by conversation."""
    rows = _rows(from_date, to_date, user=user)

    total = _blank()
    by_day, by_user, by_model, by_convo = {}, {}, {}, {}
    for r in rows:
        _add(total, r)
        _add(by_day.setdefault(r["day"], _blank()), r)
        _add(by_user.setdefault(r["user"], _blank()), r)
        _add(by_model.setdefault(r["model"] or "(unknown)", _blank()), r)
        c = by_convo.setdefault(r["conversation"], _blank())
        _add(c, r)
        c["last"] = str(r["when"])

    def listed(d, key):
        out = []
        for k, v in d.items():
            v[key] = k
            out.append(_finish(v))
        return out

    convos = listed(by_convo, "conversation")
    if convos:
        titles = {c["name"]: c for c in frappe.get_all(
            "Isoft AI Conversation",
            filters={"name": ["in", [c["conversation"] for c in convos]]},
            fields=["name", "title", "owner"], limit_page_length=0)}
        for c in convos:
            meta = titles.get(c["conversation"]) or {}
            c["title"] = meta.get("title") or c["conversation"]
            c["user"] = meta.get("owner") or ""

    return {
        "from_date": str(from_date),
        "to_date": str(to_date),
        "total": _finish(total),
        "by_day": sorted(listed(by_day, "day"), key=lambda r: r["day"]),
        "by_user": sorted(listed(by_user, "user"), key=lambda r: -r["cost"]),
        "by_model": sorted(listed(by_model, "model"), key=lambda r: -r["cost"]),
        "by_conversation": sorted(convos, key=lambda r: -r["cost"]),
        "model_assumed": _default_model(),
    }


def by_tool(from_date, to_date):
    """Tool calls in the window: how often, how slow, how often they failed."""
    rows = frappe.get_all(
        "Isoft AI Query Log",
        filters={"creation": ["between", [str(from_date) + " 00:00:00",
                                          str(to_date) + " 23:59:59"]]},
        fields=["tool", "elapsed_ms", "row_count", "error"],
        limit_page_length=0,
    )
    agg = {}
    for r in rows:
        a = agg.setdefault(r["tool"] or "(unknown)", {
            "tool": r["tool"], "calls": 0, "ms": 0, "rows": 0, "errors": 0})
        a["calls"] += 1
        a["ms"] += int(flt(r["elapsed_ms"]))
        a["rows"] += int(flt(r["row_count"]))
        if (r["error"] or "").strip():
            a["errors"] += 1
    out = []
    for a in agg.values():
        a["avg_ms"] = int(a["ms"] / a["calls"]) if a["calls"] else 0
        out.append(a)
    return sorted(out, key=lambda r: -r["calls"])


# ------------------------------------------------------------------- limits

def spent_today(user):
    """What this user has used since midnight, for the caps to act on."""
    today = nowdate()
    rows = _rows(today, today, user=user)
    bucket = _blank()
    for r in rows:
        _add(bucket, r)
    return _finish(bucket)


def spent_this_month():
    """Whole-site spend since the first of the month."""
    today = getdate(nowdate())
    rows = _rows(today.replace(day=1), today)
    bucket = _blank()
    for r in rows:
        _add(bucket, r)
    return _finish(bucket)


def check_limits(user=None):
    """Raise if this user, or the site, is over a configured cap.

    Called before the model is, so a cap that is reached costs nothing. A cap
    of 0 means no cap, which is the default on every setting.
    """
    user = user or frappe.session.user
    try:
        s = frappe.get_single("Isoft Business AI Settings")
    except Exception:
        return

    q_cap = int(flt(getattr(s, "daily_question_limit", 0)))
    t_cap = int(flt(getattr(s, "daily_token_limit", 0)))
    b_cap = flt(getattr(s, "monthly_budget_usd", 0))

    if q_cap or t_cap:
        mine = spent_today(user)
        if q_cap and mine["questions"] >= q_cap:
            frappe.throw(
                frappe._("You have reached today's limit of {0} questions "
                         "({1} asked). It resets at midnight.").format(q_cap, mine["questions"]))
        if t_cap and mine["tokens"] >= t_cap:
            frappe.throw(
                frappe._("You have reached today's token limit of {0} "
                         "({1} used). It resets at midnight.").format(t_cap, mine["tokens"]))

    if b_cap:
        month = spent_this_month()
        if month["cost"] >= b_cap:
            frappe.throw(
                frappe._("The assistant has reached this month's budget of "
                         "{0} USD ({1} spent). An administrator can raise it in "
                         "Isoft Business AI Settings.").format(b_cap, round(month["cost"], 2)))
