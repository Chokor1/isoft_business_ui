"""Guards that every tool call passes through.

The assistant is only ever as safe as this module. Three rules:

1. A tool may not run unless the *current user* can read every DocType it
   touches. Frappe's own permission system decides, not us.
2. Every company-scoped query is pinned to a company the user is allowed to
   see. An unscoped query across all companies is never issued by accident.
3. Parameters coming from the model are values, never fragments of a query.
   They are validated here and passed to ``frappe.get_list`` as bound filters.
"""

import frappe
from frappe import _

# Fields that must never reach the model or the browser through this app, even
# if a future tool selects them by mistake.
BLOCKED_FIELDS = {
    "password",
    "new_password",
    "api_key",
    "api_secret",
    "encryption_key",
    "secret",
    "access_token",
    "refresh_token",
    "private_key",
}

# DocTypes this app refuses to read under any circumstance. Frappe permissions
# would usually stop these anyway; this is the belt to that pair of braces.
BLOCKED_DOCTYPES = {
    "User",
    "User Permission",
    "Access Log",
    "Integration Request",
    "Webhook",
    "Social Login Key",
    "OAuth Bearer Token",
    "OAuth Client",
    "Token Cache",
}


class ToolPermissionError(frappe.PermissionError):
    pass


def guard_doctypes(doctypes):
    """Refuse the call unless the current user can read every DocType listed."""
    for dt in doctypes or []:
        if dt in BLOCKED_DOCTYPES:
            raise ToolPermissionError(
                _("This assistant does not read {0}.").format(dt)
            )
        if not frappe.db.exists("DocType", dt):
            # A tool referencing a DocType that is not installed on this site.
            raise ToolPermissionError(
                _("{0} is not available on this site.").format(dt)
            )
        if not frappe.has_permission(dt, "read"):
            raise ToolPermissionError(
                _("You do not have permission to read {0}.").format(dt)
            )


def allowed_companies(user=None):
    """Companies the user may query.

    If User Permissions restrict the user to specific companies, that list wins.
    Otherwise every company the user can read is allowed.
    """
    user = user or frappe.session.user
    from frappe.core.doctype.user_permission.user_permission import get_user_permissions

    perms = get_user_permissions(user) or {}
    entry = perms.get("Company") or []
    restricted = [d.get("doc") for d in entry if d.get("doc")]
    if restricted:
        return restricted

    return [c.name for c in frappe.get_list("Company", fields=["name"], limit_page_length=0)]


def resolve_company(company=None, user=None):
    """Pin a query to exactly one company the user is allowed to see.

    Never returns ``None``: a query that silently spans every company is a
    reporting bug waiting to happen, and across companies the totals are
    meaningless anyway.
    """
    permitted = allowed_companies(user)
    if not permitted:
        frappe.throw(_("You are not permitted to read any Company."), ToolPermissionError)

    if company:
        # Tolerate the model passing an abbreviation or a case variant.
        for c in permitted:
            if c.lower() == str(company).strip().lower():
                return c
        match = frappe.db.get_value("Company", {"abbr": company}, "name")
        if match and match in permitted:
            return match
        frappe.throw(
            _("Company {0} not found, or you are not permitted to see it. Available: {1}").format(
                company, ", ".join(permitted)
            ),
            ToolPermissionError,
        )

    default = frappe.defaults.get_user_default("Company", user) or frappe.db.get_single_value(
        "Global Defaults", "default_company"
    )
    if default in permitted:
        return default
    return permitted[0]


def check_fields(fields):
    """Reject any select list that reaches for a credential-shaped field."""
    for f in fields:
        lowered = str(f).lower()
        for blocked in BLOCKED_FIELDS:
            if blocked in lowered:
                frappe.throw(
                    _("Field {0} cannot be read through this assistant.").format(f),
                    ToolPermissionError,
                )
    return fields
