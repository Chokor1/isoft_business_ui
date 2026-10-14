"""Install-time setup."""

import frappe

ROLE = "Business AI User"


def after_install():
    create_role()
    seed_settings()
    frappe.db.commit()


DESCRIPTION = (
    "Can use the ISOFT business assistant: ask questions, read its answers and "
    "its history. The assistant reads data only, always within this user's own "
    "ERPNext permissions, and creates or changes nothing. Managing its settings "
    "and seeing everyone's usage is System Manager, not this role."
)


def create_role():
    if frappe.db.exists("Role", ROLE):
        # Keep the description current even where the role predates it.
        frappe.db.set_value("Role", ROLE, "desk_access", 1)
        return
    frappe.get_doc({
        "doctype": "Role",
        "role_name": ROLE,
        "desk_access": 1,
    }).insert(ignore_permissions=True)
    print("Created role: %s" % ROLE)


def seed_settings():
    """Leave the assistant switched off until a key and a model are configured.

    Only on a FIRST seed. after_install runs again on a reinstall, and an
    unconditional ``enabled = 0`` here silently switches off an assistant that
    was working - which is a surprising way to lose a live feature.
    """
    settings = frappe.get_single("Isoft Business AI Settings")
    first_run = not settings.model
    if not settings.model:
        settings.model = "claude-opus-5"
    if not settings.max_tokens:
        settings.max_tokens = 8000
    if not settings.max_iterations:
        settings.max_iterations = 6
    if not settings.effort:
        settings.effort = "medium"
    if first_run:
        settings.enabled = 0
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    print("Seeded Isoft Business AI Settings%s"
          % (" (disabled until configured)" if first_run else " (left enabled as it was)"))
