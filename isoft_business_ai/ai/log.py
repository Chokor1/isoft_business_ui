"""Logging that can never break an answer.

These calls sit inside exception handlers. A logger that raises there would
turn a recoverable tool error into a failed request, so every call is guarded.
"""

import frappe


def safe_log(level, message, exc_info=False):
    try:
        logger = frappe.logger("isoft_business_ai")
        getattr(logger, level, logger.info)(message, exc_info=exc_info)
    except Exception:
        # Logging is best-effort. Never propagate.
        pass
