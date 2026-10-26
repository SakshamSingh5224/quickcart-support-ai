"""Auditable historical QuickCart SOP checks (informational, not payment instructions)."""
from dataclasses import dataclass
from math import isfinite
from typing import Optional

COD = 'Cash on Delivery (COD)'
DAMAGED = 'Damaged / Defective Item Received'
REPLACED = 'Resolved - Replacement Sent'


def number(value) -> Optional[float]:
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class AuditFlag:
    rule: str
    explanation: str
    potential_excess_inr: float


def audit_ticket(order: dict, ticket: dict) -> list[AuditFlag]:
    """Return independently flagged violations; sums may overlap across rules."""
    status = str(order.get('delivery_status', '')).strip().upper()
    method = str(order.get('payment_method', '')).strip()
    resolution = str(ticket.get('resolution_status', '')).strip()
    issue = str(ticket.get('issue_category', '')).strip()
    amount, refund = number(order.get('order_amount')), number(ticket.get('refund_amount'))
    if refund is None or refund < 0:
        return [AuditFlag('DATA', 'Recorded cash refund is missing or invalid; manual reconciliation required.', 0)]
    flags = []
    if resolution == REPLACED and refund > .01:
        flags.append(AuditFlag('R2', 'Replacement plus cash refund on the same ticket.', round(refund, 2)))
    if method == COD and status == 'CANCELLED_BEFORE_SHIP' and refund > .01:
        flags.append(AuditFlag('R3', 'Unpaid COD cancellation must have ₹0 cash refund.', round(refund, 2)))
    if amount is None or amount <= 0:
        flags.append(AuditFlag('DATA', 'Order amount unavailable; cap and full-refund checks require manual review.', 0))
    else:
        if refund > amount + 100 + .01:
            flags.append(AuditFlag('R4', 'Recorded cash refund exceeds order amount plus ₹100.', round(refund - amount - 100, 2)))
        if issue == DAMAGED and resolution != REPLACED and refund > .01 and abs(refund - amount) > .01:
            flags.append(AuditFlag('R2', 'Damaged-item cash refund differs from full order amount.', 0))
    if status == 'DELAYED_IN_TRANSIT' and resolution == 'Resolved - Full Refund Issued' and refund > 100.01:
        flags.append(AuditFlag('R1', 'Delayed-in-transit order received cash full-refund outcome instead of voucher guidance.', round(refund - 100, 2)))
    return flags


def audit_order(order: dict, tickets: list[dict]) -> dict:
    """Account for ALL recorded tickets before showing a new refund request."""
    flags = []
    paid = 0.0
    replacement = False
    for ticket in tickets:
        paid_value = number(ticket.get('refund_amount'))
        if paid_value is not None and paid_value > 0:
            paid += paid_value
        replacement |= str(ticket.get('resolution_status', '')).strip() == REPLACED
        for flag in audit_ticket(order, ticket):
            flags.append((str(ticket.get('ticket_id', 'unknown')), flag))
    amount = number(order.get('order_amount'))
    if amount is not None and amount > 0 and paid > amount + 100 + .01:
        flags.append(('ORDER', AuditFlag('R4-review', 'Combined recorded refunds exceed the order-level cap; verify whether records represent distinct payments.', round(paid - amount - 100, 2))))
    return {'recorded_refunds_inr': round(paid, 2), 'replacement_recorded': replacement, 'flags': flags,
            'requires_reconciliation': replacement or paid > .01 or bool(flags)}
