"""Boot payload.

The desk needs to know, before rendering anything, whether the assistant is
switched on. Putting it in bootinfo avoids an extra request on every page load,
but bootinfo is cached per user in redis, so the Settings controller clears
that cache on save (see isoft_business_ai_settings.py) or a toggle would take
effect only after the cache expired.
"""

import frappe

ROLE = "Business AI User"


def boot_session(bootinfo):
    """Never raise: an exception here breaks the whole desk for every user."""
    try:
        roles = frappe.get_roles()
        # Same rule as api._check_access: the role decides. Mounting a launcher
        # for someone the API will refuse is worse than not showing it.
        can_use = ROLE in roles or frappe.session.user == "Administrator"

        settings = frappe.get_cached_doc("Isoft Business AI Settings")
        # The key lives in site_config.json, never in the form.
        provider = (settings.get("provider") or "openai").strip().lower()
        conf_key = "openai_api_key" if provider == "openai" else "anthropic_api_key"
        configured = bool(frappe.conf.get(conf_key))

        bootinfo.isoft_business_ai = {
            "enabled": bool(settings.get("enabled")),
            "configured": configured,
            "can_use": can_use,
            "is_manager": "System Manager" in roles,
        }
    except Exception:
        # Not migrated yet, or Settings missing. Treat as off.
        bootinfo.isoft_business_ai = {
            "enabled": False, "configured": False,
            "can_use": False, "is_manager": False,
        }
