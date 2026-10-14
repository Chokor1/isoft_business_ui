# Architecture

## The decision that shapes everything

The model does **not** write SQL. It chooses from a catalogue of hand-written,
permission-aware Python functions ("tools") and fills in their parameters.

Free-form text-to-SQL over ERPNext's ~900 tables reaches roughly 50-70% accuracy,
and the failures are invisible to the user: a forgotten `docstatus = 1`, a
double-counted return, a missing company filter. In accounting a confidently
wrong number is worse than no answer. Every figure this app shows comes from a
query a human wrote and validated once.

## Layers

```
Browser (floating widget on every desk page + full page: business-assistant)
  |
  |  frappe.call -> isoft_business_ai.api
  v
api.py            role check, conversation persistence, history trimming
  |
  v
ai/loop.py        the agent loop: model -> tool -> result -> model -> answer
  |               bounded by max_iterations; validates every argument
  v
ai/registry.py    tool catalogue + JSON schemas + ToolResult
  |
  v
ai/tools/*.py     the verified queries (sales, receivables, payables,
  |               purchases, stock, lookups)
  v
ai/query.py       the single door to the database
  |
  v
ai/security.py    permission guards, company scoping, field blocklist
  |
  v
frappe.get_list   Frappe's own permission + User Permission layer
```

`ai/client.py` is the only file that knows about Anthropic. Swapping providers
means rewriting that one file.

## The assistant is read-only

It answers questions. It creates and changes nothing, on any DocType.

Documents are authored in ERPNext or in the application that owns that step, so
this one exists for auditing and study: what the numbers are, what a change
would cost, where a figure came from. `ai/writes.py` keeps the guards a future
write capability would have to satisfy — notably that saving a Sales Invoice on
this site submits it and transmits it to AGT — but `WRITES_ENABLED` is `False`,
`save_draft` refuses unconditionally, and no tool calls it.

`quotation_to_target` still solves for a target total and shows the per-line
consequence, computing on a copy that is never saved. The two AGT rules that
shape it are in the constraints section below.

## Interface

Two surfaces share one rendering path (`public/js/ibai_renderer.js`), so a
table, a figure, a step chip or a document link looks identical in both:

- **Quick panel** (`public/js/ibai_widget.js`) — a launcher pinned
  bottom-right on every desk page, opening a panel docked to the right edge.
  It starts at 440px and is dragged between 380 and 640px by a grip on its
  left edge, with the width kept in `localStorage`. It sits below the desk
  navbar so ERP navigation stays reachable, and it overlays the page rather
  than replacing it. History is a drawer over the conversation; the open
  document appears as a removable chip in the header, which is the same thing
  as an `@` mention the user did not have to type.
- **Full workspace** (`page/business_assistant/`) at `/app/business-assistant`
  — a 260px collapsible history rail, an 820px reading column that wide
  results break out of, and a composer anchored to the bottom. The quick-panel
  launcher hides itself here; one assistant per screen. The panel's expand
  button opens it in a **new tab** (`window.open`, not a `target="_blank"`
  link — the v13 router hijacks clicks on `/app` links into the current tab),
  so the workspace sits beside the ERP rather than replacing it.

**Standalone chrome.** In its own tab the workspace hides the desk navbar and
page head and carries its own identity instead: the galaxy mark and the
product name in the rail, a home link back to `/app` in the header. Every rule
is scoped to `body.ibai-fullpage`, because the stylesheet stays in the document
after you navigate away and an unscoped `display: none` would follow you onto
every other desk screen; the class comes off on `page-change`, since
`on_page_hide` never fires in v13. Zeroing the container padding there also
exposes Bootstrap's `-15px` gutters on `.row.layout-main`, which must be zeroed
too or the console is 30px wider than its container at every width.

**The opening screen is deliberately short**: a company line and three
suggestions. Targets and alerts live behind one "Where you stand" control,
collapsed by default and remembered per user — six cards on every open was
noise, not a briefing. Suggestions come from `ai/suggestions.py`, a curated
catalogue where each question names the tool it is meant to reach; the list is
filtered through that tool's own `guard_doctypes`, so a question the user has
no permission to run is never offered. It rides along on the `briefing`
response rather than costing its own call.

**Typing suggests too.** `IBAI.typeahead` matches the same catalogue in the
browser, accent-insensitively, showing at most five. Nothing is pre-selected,
so Enter still sends what you typed until you arrow into the list, and it
stands down entirely while the `@` mention menu is open. Its keydown handler
uses `stopImmediatePropagation`, because the surface binds its own Enter-sends
handler on the same textarea and `stopPropagation` would not stop a sibling.

Shared behaviour: history grouped by date with search, rename and delete;
near-bottom autoscroll only, with a jump-to-latest button once the reader has
scrolled away; copy on every answer and every table; an inline failure block
that keeps the question so Retry costs one click; synthesised notification
sounds (WebAudio, so there is no asset to load).

Three things the backend cannot support are therefore **not** in the UI: token
streaming, a stop button, and live tool progress. `api.ask` is one blocking
call that reports which tools ran only once it is done, so the step chips are
drawn after the fact and never guessed.

The launcher is mounted only when the assistant can actually answer: `boot.py`
puts `enabled`, `configured`, `can_use` and `is_manager` into bootinfo, and a
disabled assistant shows no launcher at all. bootinfo is a redis hash keyed by
user, so the Settings controller clears it on save.

## Theme

One identity in two lights, called **galaxy**. Frappe server-renders
`<html data-theme="light|dark">` from the user's `desk_theme` (`www/app.html`)
and `theme_switcher.js` flips it live, so every colour is an `--ibai-*` token
pair: defaults on `:root`, overrides under `[data-theme="dark"]`. Nothing has
to be told the theme changed.

- **Dark** is deep space: the ISOFT login ground (`#05070b`), a nebula wash
  (violet top-right, `#2490EF` bottom-left) and a fourteen-point starfield on
  `.ibai-body::before` — a fixed constellation rather than a tiled pattern,
  because a repeat reads as noise and costs a paint per tile.
- **Light** is the same galaxy in daylight: white surfaces, the same primary
  and its violet companion `#7a5af0`, nebula reduced to a tint, starfield off
  (white specks on white read as dust).

The product mark is a barred spiral drawn by `IBAI.galaxy(size)` rather than
shipped as an asset, so its gradients read the theme tokens; each instance gets
its own gradient ids because SVG gradient ids are document-global. The launcher
and the empty-state mark keep a deep-space disc in **both** themes — a galaxy
on a white button washes out, and the mark should be the same object whatever
the desk is wearing.

Two traps worth keeping in mind here. The `background` shorthand resets
`background-image`, so any rule carrying the nebula uses `background-color`;
one shorthand further down the same rule silently erased it once. And the desk
paints a fixed watermark at `body::before, z-index: 1`, so an opaque surface is
not enough — `.ibai-console` needs its own stacking context.

Muted text (`--ibai-text-3`) carries timestamps, date headings and the source
line under every table. It is checked at 4.5:1 against the surfaces it actually
sits on in both themes, not just the lightest and darkest.

Every selector is prefixed `.ibai-` or scoped under `.ibai-panel` /
`.ibai-console` so nothing leaks into other ERP screens.

One deployment note: Frappe caches desk page scripts in
`localStorage["_page:business-assistant"]` with **no** `modified` check
(`pageview.js`), and only skips that cache when `developer_mode` is on. On a
production site, a change to `business_assistant.js` does not reach a browser
that has already loaded the page until its local storage is cleared.

## What the words mean

`ai/glossary.py` records what each business term means **on this installation**:
the calculation, the tool that produces it, what is easy to get wrong, and the
figure it was checked against. A field name does not carry its business meaning,
and several obvious readings are wrong here by tens of millions — invoiced sales
(invoiced, including tax) is not accounting revenue (the Income root, excluding tax),
and cost of sales is identified by `Account.account_type`, never by account name.

The six definitions that change an answer if guessed are substituted into the
**cached** system block, so they cost one cache write and nothing afterwards.
The rest are behind the `glossario` tool.

## Mentions: pick a type, then a record

Typing `@` opens a two-stage menu. With a bare term it offers **document types**
matching what was typed, in the user's own language — Frappe already translates
every doctype, so `@cli` finds Cliente and `@armazem` finds Armazém without this
app shipping a glossary of its own — alongside records matching across the
common types. Choosing a type rewrites the token to `@Customer:` and keeps the
menu open, now searching inside it.

The label is translated; the token always carries the **real** doctype, because
that is what every tool takes as a parameter. A hand-typed `@cliente:ferp` still
works: `documents.resolve_doctype` maps the translated name back.

All 280 business doctypes on the site are reachable, filtered by read
permission, with the twenty people actually mention ranked first.

**A mention of the wrong type is corrected, not refused.** `@[Customer:UNICOM,
LDA]` for a record that is really a Supplier used to come back as a flat "not
found" and the question died there. `documents.find_elsewhere` now names the
right type, and the answer opens with "UNICOM, LDA is registered as a supplier,
not a customer" and then answers the question.

## Trimmed history must not start on a tool result

Both APIs reject a tool result whose matching tool call is no longer in the
window. The trimmer knew only Anthropic's shape — `tool_result` blocks inside a
user message — and let OpenAI's `role: "tool"` messages through, so every
conversation past roughly eight turns became **permanently** unusable with
*"messages with role 'tool' must be a response to a preceeding message with
'tool_calls'"*.

`_is_tool_result` now recognises both shapes, and the OpenAI adapter drops any
tool result whose `tool_call_id` is not in the window it is about to send, so a
transcript that is already malformed cannot reach the API either.
`tests/test_history_trim.py` builds transcripts of every length from 1 to 39
turns in both shapes and asserts no window starts on an orphan; against the old
code it failed at **32 of 39** lengths.

## A list is not a ranking

Every tool that returns a ranked page offers the opposite order, because the
tail of a "largest first" page is the smallest of *that page*, never of the set.
This was not theoretical: asked for "our worst selling products", the assistant
read the bottom five rows of a best-sellers page and presented the 16th-to-20th
**best** sellers as the worst. The true answer was two items that sold nothing
at all.

| Tool | Ascending option |
|---|---|
| `vendas_por_artigo` | `valor_asc`, `quantidade_asc` |
| `vendas_por_cliente` | `valor_asc`, plus `facturas` / `facturas_asc` for counts |
| `facturas_de_venda` | `data_asc` (oldest), `valor_asc` |
| `facturas_de_compra` | `valor_asc` |
| `compras_total` | `valor_asc` |
| `contas_a_receber`, `contas_a_pagar` | `ascendente` |
| `general_ledger` | `valor`, `credito` |

The system prompt names the trap directly, and each tool's note states the
order it used. `general_ledger` **drops the running balance** when it is not in
date order: a running total down a value-sorted page is arithmetic over an
arbitrary sequence, which is worse than showing nothing.

Two related traps found in the same sweep. `procurar_conta` exists because
account names here carry their PGC number and company suffix — "Stock
Adjustment" matches nothing, the account is `78041 - Stock Adjustment - <COMPANY>`.
And `facturas_de_venda` grew `apenas_em_aberto`, because `estado='Unpaid'` is
one exact status and silently excludes everything `Overdue` — so "the oldest
invoice that still has a balance" was answered from a single row when the real
answer was fifteen months older.

## Sorting the invoice lists

`facturas_de_venda` and `facturas_de_compra` take `ordenar_por`, because asked
for "the 20 top sales invoices by amount" the invoice list could only return
the 20 most recent. The assistant handled that well — it said the rows were not
sorted by amount and so could not be treated as a top 20 — but the capability
was simply missing.

Sales: `data` (default), `valor`, `valor_asc`, `em_divida`, plus a
`valor_minimo` floor. Purchases: `vencimento` (default), `valor`, `total`.

The note now **states the order every time**, and when it is the date default it
says so in as many words: *"Sorted by date, newest first. This is NOT a ranking
by value."* A page the reader might mistake for a ranking has to say that it is
not one.

## Never let the model do arithmetic

Every tool that returns a grouped breakdown also returns its own grand total,
computed by a separate uncapped aggregate (`query.grand_total`, or
`query.grouped_total` where the figure lives on a child table). The prompt
forbids adding table rows up by hand.

This is not theoretical. On 2026-10-09 the assistant was handed eleven supplier
rows with no total, added them itself, and reported a figure **ten million out**
from the true one — stated confidently, in an answer that was
otherwise correct. Five tools had that hole; all five now carry their own total,
and the note says the table is a capped page.

## Balancete Geral

`balancete_geral` produces the Angolan PGC trial balance in the layout the
finance team already reads: movement debit, movement credit, and the closing
balance split onto its **natural side** — debit or credit, one of them always
zero, never both. Group accounts carry the rolled-up total of their sub-tree,
and each PGC class ends with *Soma Liquida* and *Soma Saldos*, then the same
pair for the report.

`financial_statement(trial_balance)` is a different shape — it returns opening
and closing as one **signed** number — which is why asking for a balancete used
to end in the assistant explaining it could not produce one.

**It does not call Isoft Insights.** The logic is reimplemented here, reading
only GL Entry, Account and Fiscal Year, for two reasons: the Insights function
gates on the Insights access list rather than on ERPNext permissions, and it
reads the ledger with raw SQL, so a user restricted to a subset of accounts
would see all of them. Everything here goes through `fetch_reference`, so the
usual permission model applies, and the tool works on a site with no Insights
app installed at all.

That only earns its place if the figures are identical, so
`tests/check_balancete.py` compares the two line for line across four
configurations and skips cleanly when Insights is absent. Current result: 112,
36, 409 and 69 accounts — **every column and every total identical**.

One trap worth keeping: `ToolResult` trims rows from the **front** at
`MAX_ROWS`, and every Soma line sits at the end. A chart big enough to hit the
cap would therefore lose exactly the totals that make it a balancete. The tool
drops account detail instead and says how many lines went.

## Feedback, and why it is inert

A user can report an answer from either surface. `api.flag_answer` stores an
**Isoft AI Feedback** record with the question, the answer, and every tool call
with its parameters, row count and source — which is exactly what a gold-set
case is made of, and `tests/feedback_report.py` prints each report already
shaped as one.

It changes nothing on its own, and the dialog says so. One person's view must
not silently alter what everyone else is told, and the audit cycles earned that
caution: **two answers that looked wrong turned out to be right**, and the query
checking them was the thing at fault. A report is evidence for a human, not a
correction.

Ownership is checked against the conversation, and only an assistant turn can be
reported.

## Why deferred tool loading is not built

The plan carried "deferred loading saves ~85% of tool tokens" from published
work on systems with hundreds of tools and no prompt caching. Measured here on
2026-10-09 it does not hold:

- prefix is 7,989 tokens (6,008 of schema across 33 tools, 1,980 of system and
  glossary), and **89% of input is served from cache** at a tenth of the price;
- a 12-tool core covers only **72%** of observed turns, so 28% would pay an
  extra model round trip to find the tool first;
- net effect: **-5.7% cost** (about $1.13 a month at 100 questions a day),
  against roughly +3s on more than a quarter of questions and a new way to pick
  the wrong tool.

Revisit it when the tool count passes about 60, or if caching stops covering the
prefix. Until then the measurement is the reason, not the literature.

## Results read as a sheet

Finance reads these tables the way they read a spreadsheet, so the table styling
follows: rules on both axes, monospaced right-aligned figures with tabular
numerals, right-aligned numeric headers, row banding, a sticky header and —
once a result has five or more columns — a frozen first column so the labels
stay put while the figures scroll.

A tool can mark a row as a subtotal or a total by putting `_style` on it
(`"subtotal"` / `"total"`). It is not a column, so it never reaches
`format_cell`; the renderer turns it into a row class. The balancete uses it for
its Soma lines, which are unreadable mixed in with the accounts they sum.
Negative figures take the danger colour.

## Role rehearsals, October

Three managers' real reporting cycles were played through the assistant and
every figure audited against the ledger: an **accounts manager** (daily ledger
and cash, weekly payables and collections, monthly close), a **sales manager**
(daily and weekly selling, pipeline, monthly report, target, margin) and a
**stock manager** (daily movement, reorder risk, dead stock, valuation).

Accuracy was exact throughout — including the sales role surfacing, unprompted,
that one customer had **227 September invoices totalling zero**, which the
ledger confirms. The failures were all missing capability:

- **No way to see money actually collected.** A general-ledger extract shows
  postings, not receipts, and the assistant said so rather than guessing. Now
  `recebimentos_pagamentos` reads Payment Entry in either direction, and an
  empty week reads as empty rather than as a missing report.
- **`despesas_revisao` could only compare with last year**, so "September versus
  August" was unanswerable. `comparar_com="periodo_anterior"` compares with the
  equal-length window immediately before.
- **No stock value per warehouse.** `stock_valor_total(por_armazem=True)` splits
  it and carries a TOTAL row.
- **"How long has it sat there" returned nothing** for an item that never moved,
  because `stock_risco` only looked inside its own window. It now reports the
  last movement *ever*, plus when the item was last received and the days idle.

## The baseline will not absorb drift

`run_gold_set.py --rebaseline` now **refuses** when any case shows logic drift,
prints what would be overwritten, and requires `--force`. This was earned: the
run that added the role-rehearsal tools rebaselined straight over seven drifted
signatures, which is exactly how a lost filter quietly becomes the expected
behaviour. The seven were reconstructed afterwards and all were intended
(`stock_valor_total` gained a filter, `stock_risco` gained columns) — but that
was reconstruction, not verification, and it should not have been necessary.

## Who can see the assistant

**`Business AI User`** is the gate, and it is the only one. The role is created
at install and its description says what it grants.

It used to be `role OR System Manager`, which on this site meant **12 people
could reach the assistant while exactly one held the role** — so the role
decided nothing. That bypass is gone. Administrator remains a safety hatch, so
the app cannot lock out the person who has to fix it.

The rule is applied at all three doors, and they agree:

- `api._check_access()` — every whitelisted endpoint.
- `boot.boot_session()` — `can_use`, which is what mounts the launcher. A
  launcher the API would refuse is worse than no launcher.
- the `business-assistant` Page's own roles.

**Managing is a separate concern.** `api._assert_manager()`, which guards the
usage console and the limits, requires **System Manager** and deliberately does
*not* call `_check_access`: auditing what the assistant costs is a management
job, and whoever does it need not be a user of it. Chaining the two meant a
System Manager had to be granted the app role before they could see the bill.

`patches/ensure_business_ai_role.py` creates the role where it is missing and
**prints exactly who loses access**, with how many conversations each of them
has, rather than taking it away silently. It grants nothing on its own; who
holds a role is an administrator's decision.

## Usage console

`/app/business-ai-usage` (System Manager only) shows what the assistant has
cost, who spent it, and the caps that stop it. Every figure is read back from
the token usage stored on each answer, including the cached portion.

**Costing counts all three streams.** Reading `input_tokens` alone understates
the bill by whatever the cache served — about 83% of input here — because the
OpenAI adapter reports it net of cached tokens. That mistake was made once in
this project's own reporting; `ai/usage.py: cost_of` is the single place it is
computed now.

Each answer stores the **model that produced it**, so cost stays attributable
after the configured model changes. Answers recorded before that field existed
are costed at the configured model, and the page says so rather than quietly
assuming.

**The controls are real.** `daily_question_limit`, `daily_token_limit` and
`monthly_budget_usd` live on Settings and are enforced by
`usage.check_limits()`, called from `api.ask` **before** the conversation is
touched and before the model is called — so a user over their cap spends
nothing and leaves no stub. 0 means no limit, which is the default on all
three. Verified: each cap refuses the ask with its own message, and with all
three cleared the same question answers again.

The daily chart is plain CSS bars on purpose. A charting library inside a
container that animates is what makes frappe-charts throw from its
ResizeObserver (see [[frappe-charts-resize-transition]] territory), and four
bars do not justify the dependency.

## Verification status

`tests/registry_status.py` prints the registry with each tool's permission
surface, its gold-set cases and whether its logic is pinned by a baseline:
**verified** (pinned), **covered** (has cases, not yet baselined), or
**experimental** (nothing pins it). 27 of 33 tools are verified; the six
experimental ones are named in the report rather than passing as approved.

`tests/run_gold_set.py --mode tools` re-checks all 85 cases against the baseline
and separates logic drift from ordinary data movement on a live site.

## Language

Source strings are **English**; `translations/pt.csv` supplies Portuguese. Users
see their own `User.language` setting. The assistant's *answers* follow the same
setting: `ai/loop.py: user_language()` feeds it into the volatile system block.

Tool and parameter descriptions are English with example phrasings in both
languages, since the model reads them rather than the user. Tool *names* stay as
they are (`vendas_total`, `contas_a_receber`) — they are stable identifiers
referenced by the gold set, the baseline and the query log.

## Security model

1. **Permissions are Frappe's job, not ours.** Every read goes through
   `frappe.get_list`, which applies role permissions *and* User Permissions.
   Verified: the same unfiltered Sales Invoice count returns fewer rows for a
   restricted user than for Administrator. The filtering is real.
2. **Read permission is checked before the tool runs.** Each tool declares the
   DocTypes it touches; `guard_doctypes` refuses the call if the current user
   cannot read any of them.
3. **Company scope is always pinned.** `resolve_company` returns exactly one
   company the user is permitted to see. A query that silently spans companies
   is a reporting bug, so it is never issued.
4. **Model arguments are values, never query fragments.** `validate_args`
   accepts only declared parameters, rejects out-of-range enums, coerces types,
   and silently drops anything the model invented.
5. **No SQL string is ever built from model output.** There is no code path
   from the model to `frappe.db.sql`.
6. **Hard blocklists** on credential-shaped fields and on DocTypes such as
   `User` and `__Auth`, as a second layer behind Frappe's own permissions.

## Correctness practices

- **`submitted()` is a named helper**, not a literal repeated in each tool.
  Forgetting `docstatus = 1` is the single most common source of wrong ERPNext
  numbers.
- **Totals are aggregated in SQL, never by summing a capped page of rows.**
  This is not theoretical: the first version of `stock_actual` reported the
  inventory as 7.89 bn AKZ against a true 8.22 bn, because it capped at 500 of
  every bin and added up a capped page of them. `stock_valor_total` and
  `ai/aging.py` exist
  specifically to make totals uncapped.
- **Aging buckets are five grouped SQL aggregates**, one per bucket, plus a
  separate uncapped grand total that stays correct even when the listed parties
  are truncated.
- **Every result carries a provenance line** ("Sales Invoice (submetidas) |
  empresa: <COMPANY> | 2026-07-01 a 2026-07-31 | devolucoes: incluidas"), shown
  in the UI under the table. A user who can verify will trust the tool; a black
  box that is right most of the time gets abandoned.
- **The table is rendered from the database result**, not retyped by the model.
  The model writes prose; the numbers come from `ToolResult.rows`.
- **Empty results hand the model a diagnosis**, not just "no rows" — wrong date
  range, unresolved name, too-narrow filter — so it can correct itself.

## The gold set

`isoft_business_ai/tests/gold_set.json` holds 53 questions covering all 15
tools, and `baseline.json` a signature of each expected result.

```bash
# 1. regression check: did any tool's numbers move? no key, no cost
env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/run_gold_set.py \
    --site <your-site> --mode tools

# after an intentional change to a tool's semantics
... --mode tools --rebaseline

# 2. full pipeline with a keyword-rule stand-in for the model. no key, no cost.
#    add --cleanup to delete the conversations it creates.
... --mode simulate

# 3. the real measure: does the model pick the right tool? costs money.
... --mode live
```

The three modes answer different questions:

| Mode | Proves | Needs a key |
|---|---|---|
| `tools` | the numbers a tool returns have not drifted | no |
| `simulate` | loop, permissions, persistence, rendering all work end to end | no |
| `live` | the *model* understands the question | yes |

`simulate` reports a tool-selection score from keyword rules. That is a **floor,
not a forecast** — it says the plumbing works and gives the real model something
to beat. Its cost figure also excludes reasoning tokens, so it understates real
spend by roughly an order of magnitude. Only `live` measures understanding, and
only `cost.py` measures spend.

## Credentials

The API key lives **only** in `sites/<site>/site_config.json`, as
`openai_api_key` or `anthropic_api_key` depending on the active provider. There
is deliberately no key field on the Settings form: the key sits with the site's
other credentials, is not editable from the desk, and never renders into a page
a user could read it from. `ai/client.py: get_api_key` reads that one place and
throws a message naming the missing config key if it is absent.

Changing the key is a `site_config.json` edit plus `bench restart` — `frappe.conf`
is read at process start.

## Routing gotcha

The desk page is `business-assistant`, **not** `isoft-business-ai`. A Workspace
claims the route matching its own label
([router.js:134](../../frappe/frappe/public/js/frappe/router.js) checks
`frappe.workspaces[route[0]]` *before* falling through to pages), so the
workspace "Isoft Business AI" would swallow a page of the same slug and render
the module card grid instead of the chat UI. Keep the two names distinct.

Related: editing a workspace JSON has no effect unless its `modified` timestamp
is bumped — migrate skips it otherwise, exactly like standard print formats.

## Known constraints

- **Python 3.8** on this bench pins the SDK to `anthropic==0.72.0`, the last
  release supporting 3.8. Newer request fields are passed via `extra_body`, and
  `output_config` support is probed once per process and disabled on rejection.
- **Frappe v13** blacklists `CONCAT`, `IF`, `IFNULL` and `COALESCE` in a field
  list as an injection guard. Period bucketing therefore selects plain
  `YEAR()`/`MONTH()`/`QUARTER()` columns and builds the label in Python. A
  `DATE_FORMAT` mask would also smuggle a `%` into the query string.
- **Plain CSS, not SCSS.** This bench's node-sass build is broken, so anything
  routed through the bundler would silently never rebuild.
