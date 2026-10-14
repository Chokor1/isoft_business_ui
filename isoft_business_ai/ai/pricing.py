"""Price solving.

The model recognises the request and names the strategy. This module does the
arithmetic, and it does it by driving ERPNext's own
``calculate_taxes_and_totals`` rather than reimplementing tax and discount
rules. Two of the three strategies cannot be solved in closed form — a discount
on net total moves the tax base, and scaled item rates round to two decimals —
so both converge numerically against the real calculation.
"""

import frappe
from frappe.utils import flt

TOLERANCE = 0.01
MAX_ITERATIONS = 10

STRATEGIES = ("net_total_discount", "item_discount", "item_rates",
              "grand_total_discount")

# Angola's AGT SAF-T rules reject a discount applied on the grand total.
# Detected from the hook rather than hard-coded, so the strategy becomes
# available again by itself if the compliance app is ever removed.
AGT_BLOCKED = {"grand_total_discount": (
    "AGT SAF-T compliance on this site rejects a discount applied on the grand "
    "total; it must be applied on items or on the net total.")}


def agt_rules_active(doctype="Quotation"):
    handlers = (frappe.get_hooks("doc_events") or {}).get(doctype, {}).get("validate") or []
    if isinstance(handlers, str):
        handlers = [handlers]
    return any("agt_validations" in str(h) for h in handlers)


def allowed_strategies(doctype="Quotation"):
    if not agt_rules_active(doctype):
        return list(STRATEGIES)
    return [s for s in STRATEGIES if s not in AGT_BLOCKED]


def _recalculate(doc):
    doc.calculate_taxes_and_totals()
    return flt(doc.grand_total)


def _set_discount(doc, x, apply_on):
    # Round to the field's own precision: the solver must search the space of
    # values the document can actually store, or it converges on a figure that
    # changes the moment it is saved.
    doc.apply_discount_on = apply_on
    doc.additional_discount_percentage = 0
    doc.discount_amount = flt(x, doc.precision("discount_amount"))
    return _recalculate(doc)


def _set_grand_discount(doc, x, _base):
    return _set_discount(doc, x, "Grand Total")


def _set_net_discount(doc, x, _base):
    return _set_discount(doc, x, "Net Total")


def _clear_margin(item):
    """ERPNext derives an item margin from any gap where rate exceeds
    price_list_rate, and AGT SAF-T rejects a non-zero item margin. Nothing this
    solver does may leave one behind.
    """
    item.margin_rate_or_amount = 0
    item.rate_with_margin = 0
    item.base_rate_with_margin = 0


def _set_rate_scale(doc, x, base):
    """Reprice: the list rate moves with the rate, so no margin is created.

    Setting only ``rate`` would make ERPNext record the difference as a margin
    the moment the new rate exceeds the old list price.
    """
    doc.discount_amount = 0
    doc.additional_discount_percentage = 0
    for item in doc.items:
        new_rate = flt(base[item.idx]["rate"] * x, item.precision("rate"))
        item.price_list_rate = new_rate
        item.rate = new_rate
        item.discount_percentage = 0
        item.discount_amount = 0
        _clear_margin(item)
    return _recalculate(doc)


def _set_item_discount(doc, x, base):
    """Discount every line by ``x`` percent off its original list price.

    The list price is left alone and the discount carries the change, which is
    the convention already used in this site's own quotations.
    """
    doc.discount_amount = 0
    doc.additional_discount_percentage = 0
    pct = max(0.0, min(100.0, flt(x)))
    for item in doc.items:
        list_rate = base[item.idx]["price_list_rate"]
        item.price_list_rate = list_rate
        item.discount_percentage = flt(pct, item.precision("discount_percentage"))
        item.discount_amount = 0
        item.rate = flt(list_rate * (1.0 - pct / 100.0), item.precision("rate"))
        _clear_margin(item)
    return _recalculate(doc)


APPLY = {
    "grand_total_discount": _set_grand_discount,
    "net_total_discount": _set_net_discount,
    "item_rates": _set_rate_scale,
    "item_discount": _set_item_discount,
}


def solve(doc, target, strategy):
    """Drive ``doc`` to ``target`` and report what was actually achieved.

    Returns (achieved_total, iterations, residual). The caller must treat the
    achieved figure as the truth: rate rounding can make an exact landing
    impossible, and saying so is better than quoting the target back.
    """
    if strategy not in APPLY:
        frappe.throw("Unknown strategy %r. Use one of: %s" % (strategy, ", ".join(STRATEGIES)))

    allowed = allowed_strategies(doc.doctype)
    if strategy not in allowed:
        frappe.throw("%s %s Use one of: %s"
                     % (AGT_BLOCKED.get(strategy, ""), "", ", ".join(allowed)))

    apply = APPLY[strategy]
    # A line with no list price gets its current rate as the base, so a
    # discount still has something to come off.
    base_rates = {i.idx: {"rate": flt(i.rate),
                          "price_list_rate": flt(i.price_list_rate) or flt(i.rate)}
                  for i in doc.items}
    start = flt(doc.grand_total)
    if start <= 0:
        frappe.throw("This document has no positive grand total to work from.")

    # A good first guess makes the common case exact in one step.
    if strategy == "item_rates":
        x0 = target / start
        x1 = x0 * 0.999
    elif strategy == "item_discount":
        if target > start:
            frappe.throw(
                "A line discount can only lower a total. %s is above the current %s — "
                "use item_rates to raise prices instead." % (target, start))
        x0 = (1.0 - target / start) * 100.0
        x1 = x0 * 1.01 if x0 else 1.0
    else:
        x0 = start - target
        x1 = x0 * 1.001 if x0 else 1.0

    f0 = apply(doc, x0, base_rates) - target
    if abs(f0) <= TOLERANCE:
        return flt(doc.grand_total), 1, 0.0

    f1 = apply(doc, x1, base_rates) - target
    iterations = 2

    while iterations < MAX_ITERATIONS and abs(f1) > TOLERANCE:
        denom = (f1 - f0)
        if not denom:
            break
        x2 = x1 - f1 * (x1 - x0) / denom
        x0, f0 = x1, f1
        x1 = x2
        f1 = apply(doc, x1, base_rates) - target
        iterations += 1

    assert_no_item_margin(doc)
    achieved = flt(doc.grand_total)
    return achieved, iterations, round(achieved - target, 2)


def assert_no_item_margin(doc):
    """Last line of defence before anything is offered or saved."""
    bad = [(i.item_code, flt(i.margin_rate_or_amount))
           for i in doc.items if flt(i.margin_rate_or_amount)]
    if bad:
        frappe.throw(
            "Repricing left a margin on %s, which AGT SAF-T rejects. "
            "This is a bug in the solver, not a data problem."
            % ", ".join("%s (%s)" % (c, m) for c, m in bad))


def describe_change(doc, strategy):
    """What the solver actually altered, for the answer's header."""
    if strategy in ("grand_total_discount", "net_total_discount"):
        return {"Discount applied": flt(doc.discount_amount),
                "Discount on": doc.apply_discount_on}
    if strategy == "item_discount":
        pcts = sorted({flt(i.discount_percentage) for i in doc.items})
        return {"Line discount %": pcts[0] if len(pcts) == 1 else pcts,
                "Lines discounted": len(doc.items)}
    return {"Line rates changed": len(doc.items),
            "List rates moved with them": "yes, so no margin is created"}


def item_costs(doc):
    """Best-effort cost per item, for the margin check.

    Valuation first, then last purchase price. Items with neither are reported
    as unknown rather than assumed to be free — a missing cost must never read
    as infinite margin.
    """
    costs = {}
    for item in doc.items:
        code = item.item_code
        if code in costs:
            continue
        value = frappe.db.sql("""
            select sum(stock_value) / nullif(sum(actual_qty), 0)
            from tabBin where item_code = %s and actual_qty > 0""", (code,))
        rate = flt(value[0][0]) if value and value[0][0] else 0.0
        if not rate:
            rate = flt(frappe.db.get_value("Item", code, "last_purchase_rate"))
        costs[code] = rate or None
    return costs


def margin_report(doc, costs):
    """Per-line margin after the new rates, flagging anything below cost."""
    lines, below = [], 0
    for item in doc.items:
        cost = costs.get(item.item_code)
        row = {
            "item_code": item.item_code,
            "qty": flt(item.qty),
            "new_rate": flt(item.rate),
            "cost": cost,
            "margin_pct": None,
            "below_cost": False,
        }
        if cost:
            row["margin_pct"] = round((flt(item.rate) - cost) / flt(item.rate) * 100, 2) \
                if flt(item.rate) else None
            row["below_cost"] = flt(item.rate) < cost
            if row["below_cost"]:
                below += 1
        lines.append(row)
    return lines, below
