# -*- coding: utf-8 -*-
"""What is verified, what is not, and when it was last checked.

The tools ARE the query registry: each one is a parameterised, permission-aware
read whose logic is pinned by the gold set. This prints that registry with its
verification state so an unverified tool cannot quietly pass as an approved one.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/registry_status.py \
        --site <your-site>
"""
from __future__ import print_function

import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(BENCH, 'apps', 'frappe'))
sys.path.insert(0, os.path.join(BENCH, 'apps', 'isoft_business_ai'))

import frappe  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True, help='Frappe site to run against')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    frappe.init(site=args.site, sites_path=os.path.join(BENCH, 'sites'))
    frappe.connect()
    frappe.set_user('Administrator')

    from isoft_business_ai.ai.registry import TOOL_REGISTRY, load_tools
    from isoft_business_ai.ai import glossary
    load_tools()

    gold = json.load(io.open(os.path.join(HERE, 'gold_set.json'), encoding='utf-8'))
    cases = {}
    for c in gold['cases']:
        cases.setdefault(c['expected_tool'], []).append(c['id'])

    baseline_path = os.path.join(HERE, 'baseline.json')
    # baseline.json is keyed by case id at the top level; its mtime is when the
    # logic signatures were last pinned.
    baseline = {}
    tested_on = 'never'
    if os.path.exists(baseline_path):
        baseline = json.load(io.open(baseline_path, encoding='utf-8'))
        tested_on = frappe.utils.get_datetime_str(
            frappe.utils.get_datetime(os.path.getmtime(baseline_path) and
                                      __import__('datetime').datetime.fromtimestamp(
                                          os.path.getmtime(baseline_path))))

    rows = []
    for name in sorted(TOOL_REGISTRY):
        spec = TOOL_REGISTRY[name]
        ids = cases.get(name, [])
        pinned = [i for i in ids if i in baseline]
        rows.append({
            'tool': name,
            'group': spec['group'],
            'reads': spec['doctypes'],
            'params': sorted(spec['input_schema']['properties']),
            'required': spec['input_schema']['required'],
            'gold_cases': ids,
            'baselined': pinned,
            'status': 'verified' if pinned else ('covered' if ids else 'experimental'),
        })

    if args.json:
        print(json.dumps({'tested_on': tested_on, 'tools': rows}, indent=1))
        frappe.destroy()
        return

    counts = {}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    print('Tool registry for %s' % args.site)
    print('Baseline last written: %s' % tested_on)
    print('Glossary verified: %s against %s' % (glossary.VERIFIED_ON, glossary.VERIFIED_SITE))
    print('%d tools: %s' % (len(rows), ', '.join('%d %s' % (n, s) for s, n in sorted(counts.items()))))
    print()
    print('%-22s %-14s %-12s %-28s %s' % ('TOOL', 'GROUP', 'STATUS', 'READS (permission)', 'GOLD CASES'))
    print('-' * 110)
    for r in rows:
        print('%-22s %-14s %-12s %-28s %s' % (
            r['tool'], r['group'], r['status'],
            ','.join(r['reads'])[:28] or '-',
            ','.join(r['gold_cases']) or '-'))
    print()
    unverified = [r['tool'] for r in rows if r['status'] == 'experimental']
    if unverified:
        print('EXPERIMENTAL - no regression case pins their logic:')
        for t in unverified:
            print('   %s' % t)
    frappe.destroy()


if __name__ == '__main__':
    main()
