"""Gold-set runner.

Two modes:

``tools``  Executes each case's expected tool with its expected arguments and
           compares the result against a stored baseline. This is the
           regression net: it catches a tool whose numbers moved because
           somebody changed a filter, and it needs no API key and costs
           nothing. Run it before every release.

``simulate`` Runs the entire pipeline — loop, tool dispatch, permission guards,
           persistence, cost accounting — with a keyword-rule stand-in instead
           of the model. No API key, no cost. Proves the plumbing works and
           gives a baseline tool-selection score the real model should beat.
           It does NOT tell you whether a real model understands the question.

``live``   Also asks the model the question and checks that it reached for the
           expected tool and produced an answer. This measures whether the
           *assistant* understands the question, which is the thing the tools
           mode cannot tell you. Costs money; needs a working API key.

Usage (from the bench directory):

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/run_gold_set.py \\
        --site <your-site> [--mode tools|live] [--rebaseline]
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

GOLD_PATH = os.path.join(HERE, "gold_set.json")
BASELINE_PATH = os.path.join(HERE, "baseline.json")

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _tokenise(value):
    """Replace concrete dates with a token.

    Tools that report "as at today" legitimately produce a different string
    every day. Comparing the raw text would flag a drift each morning, and a
    check that cries wolf daily is a check nobody reads.
    """
    if isinstance(value, str):
        return DATE_RE.sub("<date>", value)
    if isinstance(value, list):
        return [_tokenise(v) for v in value]
    if isinstance(value, dict):
        return {k: _tokenise(v) for k, v in sorted(value.items())}
    return value


def signature(result):
    """Split what a tool *does* from what the data happens to say.

    ``strict`` encodes the query logic: the select list and the filters that
    were actually applied. A dropped ``docstatus=1``, a lost company scope or a
    changed column shows up here, and any change is a failure.

    ``data`` is informational. Row counts and totals move because the business
    moves; reporting that as a failure would bury the signal.
    """
    rows = result.get("rows") or []
    numeric_total = 0.0
    for row in rows:
        for value in row.values():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric_total += float(value)

    return {
        "strict": {
            "columns": [c["key"] for c in result.get("columns") or []],
            "filters": _tokenise(result.get("filters_applied") or {}),
            "source": _tokenise(result.get("source") or ""),
        },
        "data": {
            "row_count": result.get("row_count"),
            "numeric_total": round(numeric_total, 2),
        },
    }


def run_tools_mode(cases, baseline, rebaseline, force=False):
    import frappe
    from isoft_business_ai.ai.loop import execute_tool

    results = {}
    passed = failed = errored = moved = 0
    lines = []

    for case in cases:
        cid = case["id"]
        try:
            _result, payload = execute_tool(case["expected_tool"], case["expected_args"])
            sig = signature(payload)
            results[cid] = sig
        except Exception as e:
            errored += 1
            lines.append("ERROR %-4s %-22s %s: %s"
                         % (cid, case["expected_tool"], type(e).__name__, str(e)[:120]))
            continue

        previous = baseline.get(cid)
        if previous is None:
            lines.append("NEW   %-4s %-22s rows=%s total=%s"
                         % (cid, case["expected_tool"], sig["data"]["row_count"],
                            sig["data"]["numeric_total"]))
        elif previous.get("strict") == sig["strict"]:
            passed += 1
            if previous.get("data") != sig["data"]:
                moved += 1
                lines.append("data  %-4s %-22s rows %s->%s, total %s->%s"
                             % (cid, case["expected_tool"],
                                previous["data"]["row_count"], sig["data"]["row_count"],
                                previous["data"]["numeric_total"], sig["data"]["numeric_total"]))
        else:
            failed += 1
            lines.append("DRIFT %-4s %-22s  <- query logic changed"
                         % (cid, case["expected_tool"]))
            for key in sig["strict"]:
                if previous.get("strict", {}).get(key) != sig["strict"][key]:
                    lines.append("      %s: %r" % (key, previous.get("strict", {}).get(key)))
                    lines.append("      %s: %r" % (" " * len(key), sig["strict"][key]))

    for line in lines:
        print(line)
    print("\ntools mode: %d logic unchanged, %d LOGIC DRIFT, %d errored, %d total"
          % (passed, failed, errored, len(cases)))
    if moved:
        print("            %d had data movement only (expected on a live site)" % moved)

    if rebaseline and baseline and failed and not force:
        # Rebaselining over drift is how a lost filter becomes the new truth.
        # The drift may well be intended, but it has to be looked at and said
        # out loud rather than absorbed.
        print()
        print("REFUSING to rebaseline: %d case(s) show LOGIC DRIFT." % failed)
        print("Those signatures would become the new expected behaviour without")
        print("anyone having confirmed the change is intended.")
        print("Read the drift above. If every one of them is a change you meant")
        print("to make, run again with --rebaseline --force.")
        return failed + errored

    if rebaseline or not baseline:
        json.dump(results, open(BASELINE_PATH, "w"), indent=1, sort_keys=True)
        print("baseline written to %s (%d cases)" % (BASELINE_PATH, len(results)))

    return failed + errored


def run_simulate_mode(cases, cleanup=False):
    """Full pipeline, scripted model. Exercises api.ask() including DB writes."""
    import frappe

    from isoft_business_ai import api
    from isoft_business_ai.ai import loop
    from isoft_business_ai.cost import cost_of
    from isoft_business_ai.tests.simulator import SimulatedClient

    settings = frappe.get_single("Isoft Business AI Settings")
    was_enabled = settings.enabled
    frappe.db.set_value("Isoft Business AI Settings", None, "enabled", 1)
    frappe.db.commit()

    real_client = loop.AnthropicClient
    loop.AnthropicClient = SimulatedClient

    hits = misses = errors = 0
    total_cost = 0.0
    created = []
    by_tool = {}

    try:
        for case in cases:
            try:
                out = api.ask(case["question"])
                created.append(out["conversation"])
            except Exception as e:
                errors += 1
                print("ERROR %-4s %s: %s" % (case["id"], type(e).__name__, str(e)[:130]))
                continue

            used = [r["tool"] for r in out["results"]]
            expected = case["expected_tool"]
            hit = expected in used
            hits += 1 if hit else 0
            misses += 0 if hit else 1
            total_cost += cost_of(out["usage"], "claude-opus-5")

            stats = by_tool.setdefault(expected, [0, 0])
            stats[0 if hit else 1] += 1

            print("%s %-4s %-46s" % ("OK  " if hit else "MISS", case["id"],
                                     case["question"][:46]))
            if not hit:
                print("       expected %-22s got %s" % (expected, ",".join(used) or "-"))
            rows = sum(r["row_count"] for r in out["results"])
            print("       tools=%-40s rows=%d" % (",".join(used) or "-", rows))
            print("       answer: %s" % (out["answer"] or "").split("\n")[0][:110])

        total = hits + misses
        print("\n" + "=" * 74)
        print("SIMULATE: %d/%d routed to the expected tool (%.0f%%), %d errors"
              % (hits, total, 100.0 * hits / total if total else 0, errors))
        print("simulated spend if this had been Opus 5: $%.4f (%d questions)"
              % (total_cost, total))
        print("\nper expected tool (hit/miss):")
        for tool in sorted(by_tool):
            h, m = by_tool[tool]
            print("  %-22s %d/%d" % (tool, h, h + m))
        print("\nNOTE: keyword rules, not a model. This is a floor, not a forecast.")
        print("=" * 74)
    finally:
        loop.AnthropicClient = real_client
        frappe.db.set_value("Isoft Business AI Settings", None, "enabled", was_enabled)
        if cleanup and created:
            for name in set(created):
                frappe.delete_doc("Isoft AI Conversation", name,
                                  force=True, ignore_permissions=True)
                frappe.db.sql("delete from `tabIsoft AI Message` where conversation=%s", (name,))
            print("cleaned up %d conversations" % len(set(created)))
        frappe.db.commit()

    return errors


def run_live_mode(cases):
    from isoft_business_ai.ai import loop

    correct_tool = answered = errored = 0
    for case in cases:
        try:
            out = loop.ask(case["question"])
        except Exception as e:
            errored += 1
            print("ERROR %-4s %s: %s" % (case["id"], type(e).__name__, str(e)[:140]))
            continue

        tools_used = [r["tool"] for r in out["results"]]
        hit = case["expected_tool"] in tools_used
        correct_tool += 1 if hit else 0
        answered += 1 if out["answer"] else 0
        print("%s %-4s expected=%-20s used=%-40s"
              % ("OK  " if hit else "MISS", case["id"], case["expected_tool"],
                 ",".join(tools_used) or "-"))
        print("      Q: %s" % case["question"])
        print("      A: %s" % (out["answer"] or "")[:200].replace("\n", " "))

    total = len(cases)
    print("\nlive mode: correct tool %d/%d (%.0f%%), answered %d, errors %d"
          % (correct_tool, total, 100.0 * correct_tool / total if total else 0, answered, errored))
    return total - correct_tool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", required=True)
    parser.add_argument("--mode", default="tools", choices=["tools", "simulate", "live"])
    parser.add_argument("--cleanup", action="store_true",
                        help="delete the conversations a simulate run creates")
    parser.add_argument("--rebaseline", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="allow --rebaseline to overwrite signatures that drifted")
    parser.add_argument("--user", default="Administrator")
    parser.add_argument("--only", help="Comma-separated case ids")
    args = parser.parse_args()

    import frappe

    bench_sites = os.path.abspath(os.path.join(APP_ROOT, "..", "..", "sites"))
    frappe.init(site=args.site, sites_path=bench_sites)
    frappe.connect()
    frappe.set_user(args.user)

    if not os.path.exists(GOLD_PATH):
        # The committed set is a template: the real one names this site's own
        # customers and accounts, so it is deliberately not in the repository.
        print("No gold_set.json here. It is site-specific and not committed.")
        print("Start from the template:")
        print("    cp %s %s" % (os.path.join(HERE, "gold_set.example.json"), GOLD_PATH))
        print("then edit the dates and codes for your site and run again with "
              "--rebaseline.")
        return 1
    gold = json.load(open(GOLD_PATH))
    cases = gold["cases"]
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    baseline = {}
    if os.path.exists(BASELINE_PATH):
        baseline = json.load(open(BASELINE_PATH))

    print("gold set: %d cases | site %s | user %s | mode %s\n"
          % (len(cases), args.site, args.user, args.mode))

    if args.mode == "tools":
        rc = run_tools_mode(cases, baseline, args.rebaseline, force=args.force)
    elif args.mode == "simulate":
        rc = run_simulate_mode(cases, args.cleanup)
    else:
        rc = run_live_mode(cases)

    frappe.destroy()
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
