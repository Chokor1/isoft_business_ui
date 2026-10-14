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

# A plain clone does NOT install the Python dependencies. This step is not
# optional: without it the app installs and migrates perfectly well and then
# fails the first time somebody asks a question.
./env/bin/pip install -r apps/isoft_business_ai/requirements.txt

bench --site <your-site> install-app isoft_business_ai
bench --site <your-site> migrate
bench restart
```

`bench get-app` runs that pip step for you; `git clone` does not. The same
applies after pulling an update that changes `requirements.txt`.

Installing and migrating the app need neither provider SDK — both imports are
lazy, and that is covered by a test that blocks the module and runs the whole
install, migrate and boot path. Only answering a question needs one, and if it
is missing the app says which SDK and gives the pip command rather than raising
`ModuleNotFoundError`.

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
