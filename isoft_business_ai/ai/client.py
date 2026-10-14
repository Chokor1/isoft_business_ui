"""Settings and credentials.

Transport moved to ``ai/providers``; this module decides *which* provider runs,
with what model, and on whose key.
"""

import frappe

from isoft_business_ai.ai.providers import default_model, get_provider

DEFAULT_PROVIDER = "openai"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_EFFORT = "medium"

# The one place a key is read from, per provider.
CONF_KEYS = {"openai": "openai_api_key", "anthropic": "anthropic_api_key"}


def get_settings():
    """Read the Settings single, tolerating a site where it is not migrated."""
    defaults = {
        "provider": DEFAULT_PROVIDER,
        "model": default_model(DEFAULT_PROVIDER),
        "max_tokens": DEFAULT_MAX_TOKENS,
        "effort": DEFAULT_EFFORT,
        "max_iterations": 6,
        "enabled": 0,
        "enable_web_research": 0,
    }
    try:
        doc = frappe.get_cached_doc("Isoft Business AI Settings")
    except Exception:
        return defaults

    provider = (doc.get("provider") or DEFAULT_PROVIDER).strip().lower()
    return {
        "provider": provider,
        "model": (doc.get("model") or default_model(provider)).strip(),
        "max_tokens": int(doc.get("max_tokens") or DEFAULT_MAX_TOKENS),
        "effort": (doc.get("effort") or DEFAULT_EFFORT).strip().lower(),
        "max_iterations": int(doc.get("max_iterations") or 6),
        "enabled": int(doc.get("enabled") or 0),
        "enable_web_research": int(doc.get("enable_web_research") or 0),
    }


def get_api_key(provider=None):
    """The provider's key, from site_config.json only.

    Deliberately the single source: the key lives with the site's other
    credentials, is not editable from the desk, and never reaches a form a
    user could read it from.
    """
    provider = (provider or DEFAULT_PROVIDER).strip().lower()
    conf_key = CONF_KEYS.get(provider)
    key = frappe.conf.get(conf_key) if conf_key else None
    if not key:
        frappe.throw(
            "No API key for %s. Add '%s' to "
            "sites/<site>/site_config.json and restart the bench."
            % (provider, conf_key or "api_key")
        )
    return key


def build_provider(settings=None):
    settings = settings or get_settings()
    return get_provider(settings["provider"], settings, get_api_key(settings["provider"]))


def check_connection():
    """Cheap round trip for the Settings button."""
    settings = get_settings()
    provider = build_provider(settings)
    response = provider.create(
        system_blocks=[{"type": "text", "text": "Reply with exactly: OK"}],
        messages=provider.start_messages(
            [{"type": "text", "text": "Reply with exactly: OK"}], [], "test"),
        tools=[],
    )
    return {
        "ok": True,
        "provider": settings["provider"],
        "model": response.model,
        "reply": (response.text or "").strip()[:100],
        "input_tokens": response.usage.get("input_tokens", 0),
        "output_tokens": response.usage.get("output_tokens", 0),
    }
