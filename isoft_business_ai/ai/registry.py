"""Tool registry.

A *tool* is a hand-written, permission-aware Python function that answers one
class of business question. The model never writes SQL; it only chooses a tool
and fills its parameters. Every tool declares a JSON schema so the model knows
what it may pass, and every tool returns a :class:`ToolResult` so the UI can
render the numbers itself instead of trusting the model to retype them.
"""

import frappe

TOOL_REGISTRY = {}

# Hard ceiling on rows any single tool may return. Protects the database, the
# browser, and the token bill at once.
MAX_ROWS = 500

# Rows actually serialised into the model's context. The UI still receives the
# full result; the model only needs enough to reason and comment.
MAX_ROWS_TO_MODEL = 60


class ToolResult(object):
    """Structured result of one tool call.

    ``columns`` drives rendering and formatting, ``rows`` carries the data, and
    ``meta`` records the provenance line shown to the user ("where did this
    number come from"). Keeping these separate is what lets the UI render the
    table straight from the database result.
    """

    def __init__(self, columns, rows, source, filters_applied=None, note=None,
                 header=None, links=None, aux=False, media=None, model_note=None):
        # ``model_note`` is instruction for the model and nothing else. ``note``
        # is printed under the result, so putting "never add these to an ERP
        # total" in it showed the model's own rulebook to the reader as if it
        # were part of the answer.
        self.model_note = model_note
        # ``media`` carries pictures and files that belong to a document:
        # [{kind, name, url}]. The browser shows them; the model is told only
        # that they exist and what they are called. URLs stay out of its
        # context for the same reason ``links`` does - given one, it will
        # eventually write a slightly different one into prose.
        self.media = media or []
        # ``aux`` marks a result the model needed but the reader did not ask
        # for - resolving a half-remembered name to a code, say. The model still
        # gets it and the step still shows in the provenance strip, but the
        # browser does not print its table under the answer, where it reads as
        # though it were the answer.
        self.aux = bool(aux)
        # ``header`` carries field/value pairs for a single document, which a
        # table cannot express. Rendered as a definition list above the table.
        self.header = header
        # Documents worth opening from the answer: [{label, doctype, name}].
        # The browser turns these into desk links; the model never sees a URL.
        self.links = links or []
        self.columns = columns
        self.rows = rows or []
        self.source = source
        self.filters_applied = filters_applied or {}
        self.note = note
        self.truncated = False

        if len(self.rows) > MAX_ROWS:
            self.rows = self.rows[:MAX_ROWS]
            self.truncated = True

    def as_dict(self):
        """Full payload for the browser."""
        return {
            "header": self.header,
            "links": self.links,
            "columns": self.columns,
            "rows": self.rows,
            "row_count": len(self.rows),
            "source": self.source,
            "filters_applied": self.filters_applied,
            "note": self.note,
            "truncated": self.truncated,
            "aux": self.aux,
            "media": self.media,
        }

    def for_model(self):
        """Compact payload for the model's context window."""
        rows = self.rows[:MAX_ROWS_TO_MODEL]
        payload = {
            "columns": [c["key"] for c in self.columns],
            "rows": [[r.get(c["key"]) for c in self.columns] for r in rows],
            "row_count": len(self.rows),
            "source": self.source,
            "filters_applied": self.filters_applied,
        }
        if len(self.rows) > len(rows):
            payload["note_to_model"] = (
                "Only the first %d of %d rows are shown to you. The user sees all of them. "
                "Do not claim the list is complete." % (len(rows), len(self.rows))
            )
        if self.truncated:
            payload["truncated"] = "Result hit the %d row cap; narrow the filters." % MAX_ROWS
        if self.header:
            payload["header"] = self.header
        if self.note:
            payload["note"] = self.note
        if self.model_note:
            payload["note_to_model"] = self.model_note
        if self.media:
            payload["media"] = [{"kind": m.get("kind"), "name": m.get("name")}
                                for m in self.media]
            payload["note_media"] = (
                "%d file(s) belong to this document and are already displayed to the user "
                "beneath your answer. Say what they are; never write out a URL or claim you "
                "cannot show a picture." % len(self.media))
        if not self.rows:
            payload["empty"] = (
                "No rows matched. Check whether the filters are too narrow, the date range is "
                "outside the available data, or the name you filtered on does not exist. "
                "Consider calling a lookup tool to resolve the name before giving up."
            )
        return payload


class Param(object):
    """Small helpers that build JSON-schema fragments for tool parameters."""

    @staticmethod
    def date(desc, optional=False):
        return {"type": "string", "description": desc + " Format YYYY-MM-DD.", "_optional": optional}

    @staticmethod
    def text(desc, optional=False):
        return {"type": "string", "description": desc, "_optional": optional}

    @staticmethod
    def enum(desc, values, optional=False):
        return {"type": "string", "enum": list(values), "description": desc, "_optional": optional}

    @staticmethod
    def integer(desc, optional=False):
        return {"type": "integer", "description": desc, "_optional": optional}

    @staticmethod
    def number(desc, optional=False):
        return {"type": "number", "description": desc, "_optional": optional}

    @staticmethod
    def boolean(desc, optional=False):
        return {"type": "boolean", "description": desc, "_optional": optional}


def ai_tool(name, description, params=None, doctypes=None, group="geral"):
    """Register a function as a tool the model may call.

    ``doctypes`` lists every DocType the tool reads. The loop checks read
    permission on each one *before* the function runs, so a user who cannot
    open Sales Invoice cannot reach sales figures through the assistant either.
    """
    params = params or {}

    def decorator(fn):
        properties = {}
        required = []
        for pname, spec in params.items():
            spec = dict(spec)
            optional = spec.pop("_optional", False)
            properties[pname] = spec
            if not optional:
                required.append(pname)

        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "group": group,
            "doctypes": doctypes or [],
            "handler": fn,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        fn.tool_name = name
        return fn

    return decorator


def load_tools():
    """Import every tool module so the decorators run. Idempotent."""
    from isoft_business_ai.ai.tools import (  # noqa: F401
        accounting,
        documents,
        lookups,
        operations,
        payables,
        payments,
        quotations,
        research,
        targets,
        purchases,
        receivables,
        sales,
        stock,
    )
    return TOOL_REGISTRY


def get_tool(name):
    load_tools()
    return TOOL_REGISTRY.get(name)


def tool_schemas(enabled=None):
    """Tool definitions in the shape the Anthropic API expects.

    Sorted by name so the serialised tool block is byte-stable across requests,
    which is what makes the prompt cache actually hit.
    """
    load_tools()
    out = []
    for name in sorted(TOOL_REGISTRY):
        if enabled is not None and name not in enabled:
            continue
        tool = TOOL_REGISTRY[name]
        out.append({
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        })
    return out
