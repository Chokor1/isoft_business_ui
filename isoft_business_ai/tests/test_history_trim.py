# -*- coding: utf-8 -*-
"""The history window must never start on an orphaned tool result.

Reproduces the production failure: a long OpenAI transcript trimmed to the last
N messages began with role="tool", and the API rejected the whole request with
"messages with role 'tool' must be a response to a preceeding message with
'tool_calls'". No model calls - this is pure message-shape logic.

    env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/test_history_trim.py \
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

fails = []


def note(ok, label, detail=''):
    print(('  ok   ' if ok else '  FAIL ') + '%-56s %s' % (label, detail))
    if not ok:
        fails.append(label)


def openai_turn(i):
    """One ask-and-answer in OpenAI's shape, tools and all."""
    return [
        {"role": "user", "content": "question %d" % i},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "call_%d" % i, "type": "function",
                         "function": {"name": "vendas_total", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_%d" % i, "content": "{}"},
        {"role": "assistant", "content": "answer %d" % i},
    ]


def anthropic_turn(i):
    return [
        {"role": "user", "content": "question %d" % i},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_%d" % i, "name": "vendas_total", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_%d" % i, "content": "{}"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "answer %d" % i}]},
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True)
    args = ap.parse_args()
    frappe.init(site=args.site, sites_path=os.path.join(BENCH, 'sites'))
    frappe.connect()
    frappe.set_user('Administrator')

    from isoft_business_ai.api import _trim, HISTORY_LIMIT, _is_tool_result
    from isoft_business_ai.ai.providers.openai_provider import OpenAIProvider

    # Every offset, because which message lands first depends on how many turns
    # the conversation happens to hold.
    for shape, build in (('openai', openai_turn), ('anthropic', anthropic_turn)):
        bad = []
        for turns in range(1, 40):
            history = []
            for i in range(turns):
                history.extend(build(i))
            window = _trim(history)
            if window and _is_tool_result(window[0]):
                bad.append(turns)
        note(not bad, '%s: no window starts on a tool result' % shape,
             'checked 1..39 turns (limit %d); bad at %s' % (HISTORY_LIMIT, bad[:5]) if bad
             else 'checked 1..39 turns, limit %d' % HISTORY_LIMIT)

    # The provider guard, against a transcript that is already malformed.
    orphan = [{"role": "tool", "tool_call_id": "call_gone", "content": "{}"},
              {"role": "assistant", "content": "an answer"}]
    sent = OpenAIProvider._usable_history(orphan)
    note(all(m.get("role") != "tool" for m in sent),
         'provider drops a tool result whose call is missing',
         '%d message(s) survive' % len(sent))

    paired = openai_turn(1)
    sent = OpenAIProvider._usable_history(paired)
    note(len(sent) == len(paired), 'provider keeps a properly paired tool result',
         '%d of %d' % (len(sent), len(paired)))

    print('\n%d checks failed' % len(fails))
    frappe.destroy()
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
