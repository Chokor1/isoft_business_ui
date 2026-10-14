"""Anthropic adapter.

Kept so the gold set can compare vendors on identical tools. The bench's
Python 3.8 pins this SDK at 0.72.0, so newer request fields go through
``extra_body``.
"""

import frappe
from frappe import _

from isoft_business_ai.ai.log import safe_log
from isoft_business_ai.ai.providers.base import (
    LLMResponse, Provider, ToolCall, empty_usage)

DEFAULT_MODEL = "claude-opus-5"

# Decided once per process after the API tells us whether it accepts the field.
_SUPPORTS_OUTPUT_CONFIG = None


class AnthropicProvider(Provider):
    name = "anthropic"

    def _client(self):
        # Lazy, like the OpenAI adapter: install and migrate must not need it.
        try:
            import anthropic
        except ImportError:
            frappe.throw(
                _("The Anthropic SDK is not installed on this bench, so the assistant "
                  "cannot reach the model. Install it with:\n\n"
                  "    ./env/bin/pip install 'anthropic>=0.40,<0.73'\n\n"
                  "then run bench restart."))

        self._anthropic = anthropic
        return anthropic.Anthropic(api_key=self.api_key)

    def schemas(self, tool_defs):
        return [{
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["input_schema"],
        } for t in tool_defs]

    def start_messages(self, system_blocks, history, question):
        # The system prompt is a separate request parameter here, not a message.
        messages = list(history or [])
        messages.append({"role": "user", "content": question})
        return messages

    def append_assistant(self, messages, response):
        messages.append({"role": "assistant", "content": serialise_blocks(response.raw.content)})

    def append_tool_results(self, messages, results):
        # All results for one assistant turn go back in a single user message.
        messages.append({"role": "user", "content": [{
            "type": "tool_result",
            "tool_use_id": r["id"],
            "content": r["content"],
            "is_error": r["is_error"],
        } for r in results]})

    def create(self, system_blocks, messages, tools):
        global _SUPPORTS_OUTPUT_CONFIG

        client = self._client()
        kwargs = dict(
            model=self.settings.get("model") or DEFAULT_MODEL,
            max_tokens=int(self.settings.get("max_tokens") or 8000),
            system=system_blocks,
            messages=messages,
            tools=tools,
        )

        effort = self.settings.get("effort")
        response = None
        if effort and _SUPPORTS_OUTPUT_CONFIG is not False:
            try:
                response = client.messages.create(
                    extra_body={"output_config": {"effort": effort}}, **kwargs)
                _SUPPORTS_OUTPUT_CONFIG = True
            except self._anthropic.BadRequestError as e:
                message = str(e).lower()
                if "output_config" not in message and "effort" not in message:
                    raise
                _SUPPORTS_OUTPUT_CONFIG = False
                safe_log("info", "output_config not accepted, continuing without effort")

        if response is None:
            response = client.messages.create(**kwargs)

        calls = [ToolCall(b.id, b.name, b.input)
                 for b in response.content if b.type == "tool_use"]
        text = "".join(b.text for b in response.content if b.type == "text")

        usage = empty_usage()
        for key in usage:
            usage[key] = getattr(response.usage, key, 0) or 0

        return LLMResponse(
            text=text,
            tool_calls=calls,
            usage=usage,
            wants_tools=(response.stop_reason == "tool_use"),
            model=response.model,
            raw=response,
        )


def serialise_blocks(blocks):
    """Plain dicts, so the transcript can be stored and replayed.

    ``exclude_none`` matters: replaying a block with explicit nulls in optional
    fields is rejected.
    """
    out = []
    for block in blocks:
        if isinstance(block, dict):
            out.append(block)
        elif hasattr(block, "model_dump"):
            out.append(block.model_dump(exclude_none=True))
        elif hasattr(block, "dict"):
            out.append(block.dict(exclude_none=True))
        else:
            out.append({"type": "text", "text": str(block)})
    return out
