"""Actual spend, computed from logged usage.

Every answer stores its token usage on the Isoft AI Message record, so once
real traffic exists this reports what the assistant actually cost rather than
what it was estimated to cost. Estimates are for planning; this is for billing.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/cost.py \\
        --site <your-site> --days 30
"""

import argparse
import json
import os
import sys

# USD per 1M tokens. Cache reads bill at ~0.1x input, cache writes at ~1.25x.
# Update if Anthropic changes list pricing.
PRICING = {
    # OpenAI — input / cached-input / output, USD per 1M tokens.
    "gpt-5.6-sol":     {"input": 4.00, "cached": 0.40,  "output": 20.00},
    "gpt-5.6-terra":   {"input": 2.00, "cached": 0.20,  "output": 12.00},
    "gpt-5.6-luna":    {"input": 0.20, "cached": 0.02,  "output": 1.20},
    "gpt-5.4":         {"input": 2.50, "cached": 0.25,  "output": 15.00},
    "gpt-5.4-mini":    {"input": 0.75, "cached": 0.075, "output": 4.50},
    "gpt-5.4-nano":    {"input": 0.20, "cached": 0.02,  "output": 1.25},
    "gpt-5":           {"input": 1.25, "cached": 0.125, "output": 10.00},
    "gpt-5-mini":      {"input": 0.25, "cached": 0.025, "output": 2.00},
    "gpt-5-nano":      {"input": 0.05, "cached": 0.005, "output": 0.40},
    "gpt-6-astra":     {"input": 10.00, "cached": 1.00, "output": 50.00},
    # Anthropic — cached reads bill at 0.1x input, writes at 1.25x.
    "claude-opus-5":   {"input": 5.00, "cached": 0.50,  "output": 25.00},
    "claude-sonnet-5": {"input": 2.00, "cached": 0.20,  "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "cached": 0.10, "output": 5.00},
    "claude-fable-5-1": {"input": 10.00, "cached": 1.00, "output": 50.00},
}

CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


def price_for(model):
    if model in PRICING:
        return PRICING[model]
    for key, value in PRICING.items():
        if model and model.startswith(key):
            return value
    return PRICING["gpt-5.6-terra"]


def cost_of(usage, model):
    """Cached reads are priced from the table, not derived, because the two
    vendors discount them differently."""
    p = price_for(model)
    fresh = usage.get("input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    output = usage.get("output_tokens", 0) or 0

    return (
        fresh / 1e6 * p["input"]
        + cache_read / 1e6 * p["cached"]
        + cache_write / 1e6 * p["input"] * CACHE_WRITE_MULTIPLIER
        + output / 1e6 * p["output"]
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.abspath(os.path.join(here, ".."))
    # Python puts this script's own directory on sys.path, and it contains a
    # nested isoft_business_ai/ module folder that would shadow the package.
    for entry in list(sys.path):
        if os.path.abspath(entry) == here:
            sys.path.remove(entry)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)

    import frappe
    from frappe.utils import add_days, nowdate

    sites_path = os.path.abspath(os.path.join(app_root, "..", "..", "sites"))
    frappe.init(site=args.site, sites_path=sites_path)
    frappe.connect()

    settings = frappe.get_single("Isoft Business AI Settings")
    model = settings.model or "claude-opus-5"
    since = add_days(nowdate(), -args.days)

    rows = frappe.get_all(
        "Isoft AI Message",
        filters={"role": "assistant", "creation": [">=", since]},
        fields=["name", "usage_json", "owner", "creation"],
        limit_page_length=0,
    )

    total = 0.0
    tokens = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    per_user = {}

    for row in rows:
        try:
            usage = json.loads(row.usage_json or "{}")
        except ValueError:
            continue
        c = cost_of(usage, model)
        total += c
        per_user[row.owner] = per_user.get(row.owner, 0.0) + c
        for k in tokens:
            tokens[k] += usage.get(k, 0) or 0

    answers = len(rows)
    print("model            : %s" % model)
    print("period           : last %d days (since %s)" % (args.days, since))
    print("answers          : %d" % answers)
    if not answers:
        print("\nNo answers logged yet. Ask some questions, then run this again.")
        frappe.destroy()
        return

    cached = tokens["cache_read_input_tokens"]
    prefix_total = cached + tokens["input_tokens"] + tokens["cache_creation_input_tokens"]
    hit_rate = (100.0 * cached / prefix_total) if prefix_total else 0.0

    print("input tokens     : %d fresh, %d cache read, %d cache write"
          % (tokens["input_tokens"], cached, tokens["cache_creation_input_tokens"]))
    print("output tokens    : %d" % tokens["output_tokens"])
    print("cache hit rate   : %.0f%%   (low means the prefix is being invalidated)" % hit_rate)
    print("")
    print("TOTAL            : $%.2f" % total)
    print("per answer       : $%.4f" % (total / answers))
    print("projected /month : $%.2f" % (total / args.days * 30))

    if per_user:
        print("\ntop users:")
        for user, c in sorted(per_user.items(), key=lambda kv: -kv[1])[:10]:
            print("  %-40s $%.2f" % (user, c))

    frappe.destroy()


if __name__ == "__main__":
    main()
