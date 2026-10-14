# -*- coding: utf-8 -*-
"""Prove balancete_geral agrees with the Isoft Insights report, line for line.

The assistant reimplements the Balancete Geral so it works on a site that has
no Insights app, and so every read goes through the permission-aware layer
rather than raw SQL. That only earns its place if the figures are identical.

Skips cleanly when isoft_insights is not installed - which is the whole point
of reimplementing it.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/check_balancete.py \
        --site <your-site>
"""
from __future__ import print_function

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(BENCH, 'apps', 'frappe'))
sys.path.insert(0, os.path.join(BENCH, 'apps', 'isoft_business_ai'))

import frappe  # noqa: E402

PAIRS = [
    ('abertura_debito', 'opening_debit'),
    ('abertura_credito', 'opening_credit'),
    ('mov_debito', 'debit'),
    ('mov_credito', 'credit'),
    ('saldo_debito', 'saldo_debit'),
    ('saldo_credito', 'saldo_credit'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True, help='Frappe site to run against')
    ap.add_argument('--company', default=None)
    ap.add_argument('--from-date', default='2026-01-01')
    ap.add_argument('--to-date', default='2026-10-12')
    args = ap.parse_args()

    frappe.init(site=args.site, sites_path=os.path.join(BENCH, 'sites'))
    frappe.connect()
    frappe.set_user('Administrator')

    if 'isoft_insights' not in frappe.get_installed_apps():
        print('isoft_insights is not installed here, so there is nothing to compare '
              'against. balancete_geral does not need it.')
        frappe.destroy()
        return 0

    from isoft_insights.isoft_insights.utils import get_balancete_geral
    from isoft_business_ai.ai import accounting as engine
    from isoft_business_ai.ai.security import resolve_company

    company = args.company or resolve_company()
    failures = 0

    for opening in (0, 1):
        for depth in (0, 2):
            theirs = get_balancete_geral(
                from_date=args.from_date, to_date=args.to_date, company=company,
                include_opening=opening, only_with_movement=1, max_depth=depth)
            mine = engine.balancete(
                company, from_date=args.from_date, to_date=args.to_date,
                include_opening=bool(opening), only_with_movement=True, nivel=depth)

            label = 'saldo_inicial=%d nivel=%d' % (opening, depth)
            t_acc = [r for r in theirs['rows'] if r.get('kind') == 'account']
            m_acc = [r for r in mine['rows'] if r.get('tipo') == 'conta']

            if len(t_acc) != len(m_acc):
                print('  FAIL %-26s row count %d vs %d' % (label, len(t_acc), len(m_acc)))
                failures += 1
                continue

            bad = []
            for a, b in zip(t_acc, m_acc):
                if (a.get('number') or a.get('account')) != b['conta']:
                    bad.append('account order: %s vs %s' % (a.get('number'), b['conta']))
                    continue
                for mine_f, theirs_f in PAIRS:
                    x, y = round(float(a.get(theirs_f) or 0), 2), round(float(b[mine_f]), 2)
                    if abs(x - y) > 0.005:
                        bad.append('%s %s: %s vs %s' % (b['conta'], mine_f, x, y))

            for mine_f, theirs_f in PAIRS:
                x = round(float(theirs['totals'].get(theirs_f) or 0), 2)
                y = round(float(mine['totals'].get(mine_f) or 0), 2)
                if abs(x - y) > 0.005:
                    bad.append('TOTAL %s: %s vs %s' % (mine_f, x, y))

            if bad:
                print('  FAIL %-26s %d difference(s)' % (label, len(bad)))
                for b in bad[:6]:
                    print('         %s' % b)
                failures += 1
            else:
                print('  ok   %-26s %d accounts, every column and total identical'
                      % (label, len(m_acc)))

    print()
    print('%d comparison(s) failed' % failures)
    frappe.destroy()
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
