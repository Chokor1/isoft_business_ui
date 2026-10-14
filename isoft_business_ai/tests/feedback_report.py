# -*- coding: utf-8 -*-
"""Reported answers, with what would be needed to turn one into a test case.

Feedback changes nothing on its own. This is the bridge: it prints each report
with the tool call that produced it, already shaped like a gold_set.json case,
so a confirmed fault becomes a regression test rather than a memory.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/feedback_report.py \
        --site <your-site> [--status New]
"""
from __future__ import print_function

import argparse
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
    ap.add_argument('--status', default=None, help='New, Investigating, Confirmed, Fixed')
    ap.add_argument('--limit', type=int, default=50)
    args = ap.parse_args()

    frappe.init(site=args.site, sites_path=os.path.join(BENCH, 'sites'))
    frappe.connect()
    frappe.set_user('Administrator')

    filters = {}
    if args.status:
        filters['status'] = args.status
    rows = frappe.get_all(
        'Isoft AI Feedback', filters=filters,
        fields=['name', 'verdict', 'status', 'owner', 'reported_on', 'question',
                'comment', 'tools_json', 'company', 'conversation'],
        order_by='reported_on desc', limit_page_length=args.limit)

    if not rows:
        print('No feedback%s. Nothing to investigate.'
              % (' with status %s' % args.status if args.status else ''))
        frappe.destroy()
        return

    by_verdict = {}
    for r in rows:
        by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1
    print('%d report(s): %s\n' % (len(rows), ', '.join(
        '%d %s' % (n, v) for v, n in sorted(by_verdict.items(), key=lambda x: -x[1]))))

    for r in rows:
        print('=' * 76)
        print('%s  %s  [%s]  by %s on %s' % (r.name, r.verdict, r.status, r.owner,
                                             r.reported_on))
        print('  company      : %s' % r.company)
        print('  question     : %s' % (r.question or '').replace('\n', ' ')[:140])
        if r.comment:
            print('  they say     : %s' % r.comment.replace('\n', ' ')[:200])
        try:
            tools = json.loads(r.tools_json or '[]')
        except ValueError:
            tools = []
        if not tools:
            print('  tools        : none ran - the assistant answered without reading data')
            continue
        for t in tools:
            print('  tool         : %s  (%s rows, %sms)'
                  % (t.get('tool'), t.get('rows'), t.get('elapsed_ms')))
            print('    parameters : %s' % json.dumps(t.get('arguments'), ensure_ascii=False))
            print('    source     : %s' % (t.get('source') or '')[:110])
        first = tools[0]
        print('  gold case    : %s' % json.dumps({
            'id': 'FB-' + r.name[:6].upper(),
            'question': (r.question or '')[:160],
            'expected_tool': first.get('tool'),
            'expected_args': first.get('arguments'),
            'note': 'From feedback %s: %s' % (r.name, (r.comment or r.verdict)[:90]),
        }, ensure_ascii=False))

    print()
    print('Confirm a fault before acting on it. Reproduce the tool call above against the')
    print('ledger first: in six audit cycles, two answers that looked wrong were right and')
    print('the checking query was the thing at fault.')
    frappe.destroy()


if __name__ == '__main__':
    main()
