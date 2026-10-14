# -*- coding: utf-8 -*-
"""Why the assistant is not answering, from the command line.

Written after a missing provider SDK surfaced as a bare ModuleNotFoundError on
a production bench, where the desk was the last place anyone wanted to debug
from. Reports every precondition and exits non-zero if any fails.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/readiness_check.py \
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True, help='Frappe site to check')
    ap.add_argument('--user', default='Administrator',
                    help='Check as this user (default Administrator)')
    args = ap.parse_args()

    frappe.init(site=args.site, sites_path=os.path.join(BENCH, 'sites'))
    frappe.connect()
    frappe.set_user(args.user)

    from isoft_business_ai import api

    try:
        report = api.readiness()
    except Exception as e:
        print('Could not run the check as %s: %s: %s'
              % (args.user, type(e).__name__, e))
        frappe.destroy()
        return 2

    print('Isoft Business AI on %s, as %s' % (args.site, args.user))
    print('Provider: %s' % report['provider'])
    print('')
    for c in report['checks']:
        print('  %-4s %-34s %s' % ('ok' if c['ok'] else 'FAIL', c['check'], c['detail']))
    print('')
    if report['ready']:
        print('Ready. If a question still fails, the error is in the answer path, '
              'not the setup - check the Isoft AI Query Log.')
    else:
        print('Not ready. Fix the FAIL lines above, then run bench restart: '
              'gunicorn runs with --preload, so a Python change needs it.')
    frappe.destroy()
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
