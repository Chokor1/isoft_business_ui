"""What the ERP's own reports ask, and whether the assistant can answer it.

The question of "what should this thing be able to answer" has an authoritative
local answer: the standard reports shipped with the ERP. Somebody already
decided those are the questions a business asks, and every one of them is a
question a user can reasonably put to the assistant in words.

This walks that catalogue and matches it against the tool registry, so gaps are
found here rather than one at a time by someone hitting them in production.
Matching is by the data each side reads - a report's ref_doctype against the
doctypes a tool declares - plus a keyword pass over the names. It is a guide,
not a verdict: a covered report may still be answered badly, and an uncovered
one may not be worth a tool. Read the uncovered list and decide.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/report_coverage.py \
        --site dev.isoft.ao [--module Accounts] [--all]
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

BUSINESS_MODULES = ["Accounts", "Selling", "Buying", "Stock", "Manufacturing",
                    "CRM", "Projects", "Assets", "Support"]

# Reports that are not questions about the business: setup lists, print aids,
# and per-customer one-offs that were built for one site.
SKIP_WORDS = ("template", "print", "settings", "tool", "log", "trial run")


def tool_index(registry):
    """doctype -> tools that read it, and a bag of words per tool."""
    by_doctype, words = {}, {}
    for name, tool in registry.load_tools().items():
        for dt in (tool.get("doctypes") or []):
            by_doctype.setdefault(dt, []).append(name)
        words[name] = set(
            (name + " " + (tool.get("description") or "")).lower().split())
    return by_doctype, words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--module", action="append")
    ap.add_argument("--all", action="store_true",
                    help="list the covered reports too, not only the gaps")
    args = ap.parse_args()

    import frappe

    frappe.init(site=args.site, sites_path="sites")
    frappe.connect()
    frappe.set_user("Administrator")

    from isoft_business_ai.ai import registry

    by_doctype, words = tool_index(registry)
    modules = args.module or BUSINESS_MODULES

    reports = frappe.get_all(
        "Report", filters={"disabled": 0, "module": ["in", modules]},
        fields=["name", "ref_doctype", "module"], limit_page_length=0)

    covered, gaps = [], []
    for r in sorted(reports, key=lambda r: (r["module"], r["name"])):
        low = r["name"].lower()
        if any(w in low for w in SKIP_WORDS):
            continue
        tools = list(by_doctype.get(r["ref_doctype"], []))
        # A shared doctype is weak evidence on its own: Sales Invoice backs a
        # dozen different questions. Prefer a tool whose own words overlap the
        # report's name.
        terms = set(low.replace("-", " ").split()) - {"report", "wise", "and", "by"}
        strong = [t for t in tools if terms & words.get(t, set())]
        (covered if strong else gaps).append((r["module"], r["name"], strong or tools))

    print("%d reports in %s" % (len(covered) + len(gaps), ", ".join(modules)))
    print("   %d matched by name to a tool, %d not" % (len(covered), len(gaps)))
    print()
    if args.all:
        print("COVERED")
        for mod, name, tools in covered:
            print("  %-13s %-46s %s" % (mod, name[:46], ",".join(tools[:2])))
        print()
    print("NOT MATCHED - read these and decide")
    last = None
    for mod, name, tools in gaps:
        if mod != last:
            print("  --- %s" % mod)
            last = mod
        print("  %-48s %s" % (name[:48], "reads " + (tools and "" or "") +
                              (",".join(tools[:2]) or "(no tool reads its doctype)")))
    frappe.destroy()


if __name__ == "__main__":
    main()
