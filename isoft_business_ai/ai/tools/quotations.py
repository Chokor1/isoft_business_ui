"""Quotation price analysis.

Read-only by decision: quotations are created in another application, and this
assistant exists for auditing and study. So this computes exactly what it would
take to reach a target and shows the per-line consequence — and writes nothing.

The arithmetic still runs through ERPNext's own
``calculate_taxes_and_totals`` rather than a reimplementation, because a number
offered to a salesperson has to match what the document would actually say.
"""

import frappe
from frappe.utils import flt

from isoft_business_ai.ai import pricing
from isoft_business_ai.ai.formatting import currency, number, text
from isoft_business_ai.ai.registry import Param, ToolResult, ai_tool


@ai_tool(
    name="quotation_to_target",
    description=(
        "Work out how to make a quotation's grand total reach a target amount. Use when "
        "the user says a quotation should come to a specific figure — 'what discount gets "
        "this to 2,000,000', 'what would the prices need to be for 42 million'. Returns "
        "the exact change per line and flags anything below cost. "
        "CALCULATES ONLY: it never creates, modifies or saves any document. If the user "
        "asks you to save or apply it, say that the change has to be made in ERPNext."
    ),
    params={
        "quotation": Param.text("The quotation's exact name/id."),
        "target_total": Param.text("The grand total to reach, as a plain number."),
        "strategy": Param.enum(
            "How to reach it. 'net_total_discount' (default) is one document discount "
            "before tax. 'item_discount' is the same percentage off each line's list "
            "price, which is how this company's quotations express a discount. "
            "'item_rates' changes the unit prices themselves. 'grand_total_discount' is "
            "rejected by AGT SAF-T compliance here.",
            list(pricing.STRATEGIES), optional=True),
    },
    doctypes=["Quotation"],
    group="quotations",
)
def quotation_to_target(quotation, target_total, strategy="net_total_discount"):
    target = flt(str(target_total).replace(",", "").replace(" ", ""))
    if target <= 0:
        frappe.throw("The target total must be a positive number.")

    if not frappe.has_permission("Quotation", "read", doc=quotation):
        frappe.throw("You do not have permission to read Quotation %s." % quotation,
                     frappe.PermissionError)

    original = frappe.get_doc("Quotation", quotation)
    before_rates = {i.item_code: flt(i.rate) for i in original.items}
    before_total = flt(original.grand_total)

    # Solved on a copy, which is never saved. The original is untouched even in
    # memory, so a bug here cannot alter a real quotation.
    draft = frappe.copy_doc(original)
    achieved, iterations, residual = pricing.solve(draft, target, strategy)

    costs = pricing.item_costs(draft)
    margin_lines, below_cost = pricing.margin_report(draft, costs)

    rows = []
    for line in margin_lines:
        old_rate = before_rates.get(line["item_code"], 0.0)
        rows.append({
            "item_code": line["item_code"],
            "qty": line["qty"],
            "old_rate": old_rate,
            "new_rate": line["new_rate"],
            "change_pct": round((line["new_rate"] - old_rate) / old_rate * 100, 2) if old_rate else None,
            "cost": line["cost"],
            "margin_pct": line["margin_pct"],
            "below_cost": "YES" if line["below_cost"] else "",
        })

    notes = ["Nothing was changed: apply this in ERPNext if you want it."]
    if abs(residual) > 0.01:
        notes.append(
            "Cannot land exactly: off by %s, because line rates round to the field's "
            "precision. A net total discount gets closest." % residual)
    if below_cost:
        notes.append("%d line(s) fall below known cost." % below_cost)
    if any(line["cost"] is None for line in margin_lines):
        notes.append("Some items have no known cost, so their margin is unverified.")

    header = {
        "Quotation": quotation,
        "Customer": original.get("customer_name") or original.get("party_name"),
        "Current grand total": before_total,
        "Target": target,
        "Achieved (calculated)": achieved,
        "Strategy": strategy,
        "Solver passes": iterations,
    }
    header.update(pricing.describe_change(draft, strategy))

    return ToolResult(
        links=[{"label": "Open %s" % quotation, "doctype": "Quotation", "name": quotation}],
        columns=[
            text("item_code", "Item"),
            number("qty", "Qty"),
            currency("old_rate", "Old rate"),
            currency("new_rate", "New rate"),
            number("change_pct", "Change %"),
            currency("cost", "Cost"),
            number("margin_pct", "Margin %"),
            text("below_cost", "Below cost"),
        ],
        rows=rows,
        source="Quotation %s | strategy: %s | %d passes | calculated, not saved"
               % (quotation, strategy, iterations),
        filters_applied={"quotation": quotation, "target_total": target, "strategy": strategy},
        header=header,
        note=" ".join(notes),
    )
