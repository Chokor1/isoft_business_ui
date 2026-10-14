## Isoft Business AI

Conversational business intelligence for ERPNext.

Users ask a question in plain language (Portuguese or English). The assistant
picks from a catalogue of **verified query tools** — hand-written, permission-aware
Python functions — fills in the parameters, inspects the result, and answers.

It does **not** let the model invent SQL against the raw schema. Every number
shown is produced by a query a human wrote and validated, executed under the
asking user's own Frappe permissions.

See `docs/ARCHITECTURE.md`.

#### License

MIT

## Install

The repository is named `isoft_business_ui`; the Frappe app inside it is
`isoft_business_ai`, and Frappe requires the directory to match the app name:

```bash
cd ~/frappe-bench
git clone https://github.com/Chokor1/isoft_business_ui.git apps/isoft_business_ai
bench --site <your-site> install-app isoft_business_ai
```

Both provider SDKs are declared in `requirements.txt`, so `bench get-app`
installs them. If the bench already had the app and you are only pulling, run
`./env/bin/pip install -r apps/isoft_business_ai/requirements.txt` as well —
otherwise the first question raises a missing-SDK error. Nothing about
installing or migrating the app needs either SDK; only answering a question
does, and the app says so plainly if one is absent.

Put the provider key in `sites/<your-site>/site_config.json` — never in a form
field, and never in this repository:

```json
{ "openai_api_key": "sk-..." }
```

Then enable the assistant in **Isoft Business AI Settings** and grant the
**Business AI User** role to whoever should see it. A `bench restart` is needed
after changing the key, because gunicorn runs with `--preload`.

## Tests

```bash
cp apps/isoft_business_ai/isoft_business_ai/tests/gold_set.example.json \
   apps/isoft_business_ai/isoft_business_ai/tests/gold_set.json
env/bin/python apps/isoft_business_ai/isoft_business_ai/tests/run_gold_set.py \
    --site <your-site> --mode tools --rebaseline
```

`gold_set.json` and `baseline.json` are **not** committed: they name a specific
installation's customers, suppliers and accounts and store its real figures.
Start from the template, point it at your own data, and pin the baseline. After
that, `--mode tools` reports logic drift separately from ordinary data movement,
and `--rebaseline` refuses to overwrite a drifted signature without `--force`.

| Script | What it does |
|---|---|
| `tests/run_gold_set.py` | Regression over every tool; logic drift vs data movement |
| `tests/registry_status.py` | Each tool's permissions, cases and verification state |
| `tests/check_balancete.py` | Balancete Geral against the Isoft Insights report, if installed |
| `tests/feedback_report.py` | Reported answers, shaped as ready-made regression cases |
