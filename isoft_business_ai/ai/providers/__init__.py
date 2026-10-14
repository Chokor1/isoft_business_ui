"""Provider registry."""

import frappe

PROVIDERS = {}


def get_provider(name, settings, api_key):
    name = (name or "openai").strip().lower()
    if not PROVIDERS:
        from isoft_business_ai.ai.providers.anthropic_provider import AnthropicProvider
        from isoft_business_ai.ai.providers.openai_provider import OpenAIProvider

        PROVIDERS["openai"] = OpenAIProvider
        PROVIDERS["anthropic"] = AnthropicProvider

    cls = PROVIDERS.get(name)
    if not cls:
        frappe.throw("Unknown provider: %s. Use 'openai' or 'anthropic'." % name)
    return cls(settings, api_key)


def default_model(name):
    name = (name or "openai").strip().lower()
    if name == "anthropic":
        from isoft_business_ai.ai.providers.anthropic_provider import DEFAULT_MODEL
        return DEFAULT_MODEL
    from isoft_business_ai.ai.providers.openai_provider import DEFAULT_MODEL
    return DEFAULT_MODEL
