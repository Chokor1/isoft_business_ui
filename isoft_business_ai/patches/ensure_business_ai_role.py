# -*- coding: utf-8 -*-
"""Make sure the role exists, and say who is about to lose the assistant.

Until now a System Manager could use the assistant without holding the role,
so on an existing site the role gates nothing and removing that bypass silently
takes the assistant away from people who have it today. This patch creates the
role where it is missing and prints exactly who is affected; it grants nothing
on its own, because handing out a role is an administrator's decision.
"""

import frappe

ROLE = "Business AI User"


def execute():
    from isoft_business_ai.install import create_role

    create_role()
    frappe.db.commit()

    holders = {r[0] for r in frappe.db.sql(
        """select hr.parent from `tabHas Role` hr join tabUser u on u.name = hr.parent
           where hr.role = %s and u.enabled = 1 and u.user_type = 'System User'""", ROLE)}
    managers = {r[0] for r in frappe.db.sql(
        """select hr.parent from `tabHas Role` hr join tabUser u on u.name = hr.parent
           where hr.role = 'System Manager' and u.enabled = 1
             and u.user_type = 'System User'""")}
    losing = sorted(managers - holders - {"Administrator"})
    if not losing:
        return

    print("")
    print("The %s role now decides who may use the assistant." % ROLE)
    print("%d System Manager(s) could reach it before and no longer can:" % len(losing))
    for user in losing:
        used = frappe.db.count("Isoft AI Conversation", {"owner": user})
        print("   %-40s %s" % (user, ("%d conversation(s)" % used) if used else "never used it"))
    print("Grant the role from the User record to restore access.")
    print("")
