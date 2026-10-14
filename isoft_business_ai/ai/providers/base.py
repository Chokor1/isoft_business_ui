"""Provider interface.

The loop never looks inside a message list. It asks the provider to build one,
to append an assistant turn, and to append tool results; each provider renders
the conversation in its own vendor's shape. Everything the loop *does* read —
the text, the tool calls, the usage — comes back normalised.
"""


class ToolCall(object):
    """One tool invocation, normalised across vendors.

    ``arguments`` is always a dict. OpenAI delivers it as a JSON string, so the
    provider parses it before the loop ever sees it.
    """

    def __init__(self, id, name, arguments):
        self.id = id
        self.name = name
        self.arguments = arguments or {}


class LLMResponse(object):
    def __init__(self, text, tool_calls, usage, wants_tools, model, raw=None):
        self.text = text or ""
        self.tool_calls = tool_calls or []
        self.usage = usage or {}
        self.wants_tools = bool(wants_tools)
        self.model = model
        self.raw = raw


def empty_usage():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


class Provider(object):
    """Subclasses own the wire format and nothing else."""

    name = "base"

    def __init__(self, settings, api_key):
        self.settings = settings
        self.api_key = api_key

    # -- schemas ---------------------------------------------------------
    def schemas(self, tool_defs):
        """Render tool definitions in this vendor's shape."""
        raise NotImplementedError

    # -- messages --------------------------------------------------------
    def start_messages(self, system_blocks, history, question):
        """Build the request's message list.

        ``history`` is the stored transcript for this conversation, already in
        this provider's shape, and never contains the system prompt — each
        provider decides where that goes.
        """
        raise NotImplementedError

    def append_assistant(self, messages, response):
        raise NotImplementedError

    def append_tool_results(self, messages, results):
        """``results``: [{"id", "content", "is_error"}]."""
        raise NotImplementedError

    def strip_system(self, messages):
        """Return the transcript to store: everything except the system prompt."""
        return messages

    # -- call ------------------------------------------------------------
    def create(self, system_blocks, messages, tools):
        raise NotImplementedError
