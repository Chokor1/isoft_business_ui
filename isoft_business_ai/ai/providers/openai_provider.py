"""OpenAI adapter.

Four things differ from Anthropic and all four live here: the schema wrapper,
tool calls arriving on the message rather than as content blocks, arguments
arriving as a JSON string, and tool results going back as their own messages.
"""

import json

from isoft_business_ai.ai.log import safe_log
from isoft_business_ai.ai.providers.base import (
    LLMResponse, Provider, ToolCall, empty_usage)

DEFAULT_MODEL = "gpt-5.6-terra"

# Reasoning models reject function tools on /v1/chat/completions unless
# reasoning_effort is "none". Decided once per process: some models do not
# accept the parameter at all.
_SEND_REASONING_EFFORT = None


class OpenAIProvider(Provider):
    name = "openai"

    def _client(self):
        from openai import OpenAI

        return OpenAI(api_key=self.api_key)

    # -- schemas ---------------------------------------------------------
    def schemas(self, tool_defs):
        out = []
        for t in tool_defs:
            out.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })
        return out

    # -- messages --------------------------------------------------------
    def start_messages(self, system_blocks, history, question):
        # Stable block first, then the volatile one: OpenAI caches on the token
        # prefix, so anything that changes per user must come after what does not.
        messages = [{"role": "system", "content": b["text"]} for b in system_blocks]
        messages.extend(history or [])
        messages.append({"role": "user", "content": question})
        return messages

    def strip_system(self, messages):
        return [m for m in messages if m.get("role") != "system"]

    def append_assistant(self, messages, response):
        msg = {"role": "assistant", "content": response.text or None}
        if response.tool_calls:
            msg["tool_calls"] = [{
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": json.dumps(c.arguments, default=str)},
            } for c in response.tool_calls]
        messages.append(msg)

    def append_tool_results(self, messages, results):
        # One message per call, in the order the model asked for them.
        for r in results:
            messages.append({
                "role": "tool",
                "tool_call_id": r["id"],
                "content": r["content"],
            })

    # -- call ------------------------------------------------------------
    def create(self, system_blocks, messages, tools):
        global _SEND_REASONING_EFFORT

        kwargs = dict(
            model=self.settings.get("model") or DEFAULT_MODEL,
            messages=messages,
            max_completion_tokens=int(self.settings.get("max_tokens") or 8000),
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        client = self._client()
        response = None

        if tools and _SEND_REASONING_EFFORT is not False:
            try:
                response = client.chat.completions.create(
                    reasoning_effort="none", **kwargs)
                _SEND_REASONING_EFFORT = True
            except Exception as e:
                if "reasoning_effort" not in str(e):
                    raise
                # This model does not take the parameter; stop sending it.
                _SEND_REASONING_EFFORT = False
                safe_log("info", "reasoning_effort rejected, continuing without it")

        if response is None:
            response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        calls = []
        for c in (msg.tool_calls or []):
            try:
                args = json.loads(c.function.arguments or "{}")
            except ValueError:
                # Malformed arguments are the model's error, not a crash. The
                # loop reports it back and lets the model correct itself.
                args = {"__parse_error__": c.function.arguments}
            calls.append(ToolCall(c.id, c.function.name, args))

        usage = empty_usage()
        u = getattr(response, "usage", None)
        if u:
            usage["input_tokens"] = getattr(u, "prompt_tokens", 0) or 0
            usage["output_tokens"] = getattr(u, "completion_tokens", 0) or 0
            details = getattr(u, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) if details else 0
            usage["cache_read_input_tokens"] = cached or 0
            # OpenAI caches implicitly; uncached input is what is billed in full.
            usage["input_tokens"] = max(0, usage["input_tokens"] - (cached or 0))

        return LLMResponse(
            text=msg.content or "",
            tool_calls=calls,
            usage=usage,
            wants_tools=bool(calls),
            model=response.model,
            raw=response,
        )
