"""Deterministic QuickCart SOP decision engine. No external LLM/API required."""
import re
from dataclasses import dataclass
from typing import Optional
from math import isfinite
from policy_audit import audit_order

@dataclass(frozen=True)
class Decision:
    category: str
    headline: str
    explanation: str
    action: str
    eligible_refund: Optional[float] = None
    voucher: float = 0.0
    manual_review: bool = False


def classify_question(question: str) -> str:
    q = question.lower().strip()
    if re.search(r'broken|damag|defect|replace|faulty|crack', q):
        return 'damage'
    if re.search(r'cancel|cod|cash on delivery', q):
        return 'cancel'
    if re.search(r'refund|money back|reimburse|charged|payment', q):
        return 'refund'
    if re.search(r'where|track|deliver|ship|lost|late|delay|arriv|status', q):
        return 'tracking'
    return 'general'


def decide(order: dict, question: str, ticket: Optional[dict] = None, all_tickets: Optional[list[dict]] = None) -> Decision:
    """Informational eligibility guidance based on the four written SOP rules.

    This function cannot trigger a financial refund, replacement, voucher, or courier update.
    """
    status = str(order.get('delivery_status', '')).strip().upper()
    payment = str(order.get('payment_method', '')).strip()
    raw = order.get('order_amount')
    try:
        amount = float(raw)
        if not isfinite(amount) or amount <= 0:
            amount = None
    except (ValueError, TypeError):
        amount = None
    intent = classify_question(question)
    # Historical records are not proof of settled payments. Pause any new
    # refund/replacement recommendation until an agent reconciles them.
    history = all_tickets if all_tickets is not None else ([ticket] if ticket else [])
    history_audit = audit_order(order, history)
    if history_audit['requires_reconciliation']:
        return Decision(intent, 'Existing support history — agent review required',
                        f"This order has ₹{history_audit['recorded_refunds_inr']:,.2f} in recorded historical cash refunds"
                        + (' and a recorded replacement.' if history_audit['replacement_recorded'] else '.')
                        + ' These records must be verified before any additional refund or replacement is considered.',
                        'Request historical resolution review', manual_review=True)
    if amount is None:
        return Decision(intent, 'Manual review required',
                        'The order amount is missing or invalid. We cannot calculate a safe refund amount.',
                        'Request an agent review', manual_review=True)

    if payment == 'Cash on Delivery (COD)' and status == 'CANCELLED_BEFORE_SHIP':
        return Decision(intent, 'No cash refund due',
                        'This cash-on-delivery order was cancelled before shipping, so no payment was collected. Rule 3 requires a ₹0 refund.',
                        'Get cancellation confirmation', eligible_refund=0)

    if status in ('LOST_IN_TRANSIT', 'RETURNED_TO_SELLER'):
        # Voucher is discretionary and only for an actual resolution over 24h.
        late = bool(ticket and str(ticket.get('is_open', '')).strip().lower() in ('false','0')
                    and _float(ticket.get('resolution_hours')) is not None
                    and _float(ticket.get('resolution_hours')) > 24)
        return Decision(intent, 'Full refund eligible',
                        f'Your order is {status.replace("_", " ").lower()}. Rule 1 allows a full ₹{amount:,.2f} refund.' +
                        (' An additional ₹100 apology voucher may be offered because the historical ticket took more than 24 hours to resolve.' if late else ' A ₹100 late-resolution voucher is only considered after a ticket takes more than 24 hours to resolve.'),
                        'Request full refund review', eligible_refund=amount,
                        voucher=100 if late else 0)

    if status == 'DELAYED_IN_TRANSIT':
        return Decision(intent, 'Delivery delayed — wait 48 hours',
                        'Rule 1 says not to issue a full cash refund while the parcel is still in transit. The prescribed support remedy is a ₹100 apology voucher and a request to wait 48 hours.',
                        'Request ₹100 voucher review', eligible_refund=0, voucher=100)

    if intent == 'damage' or (ticket and str(ticket.get('issue_category')) == 'Damaged / Defective Item Received'):
        return Decision(intent, 'Replacement or full refund — choose one',
                        f'Rule 2 allows either a free replacement with ₹0 cash refund, OR a full cash refund of ₹{amount:,.2f}. Both cannot be granted for the same order. Evidence and agent approval are required.',
                        'Request damage resolution review', eligible_refund=amount, manual_review=True)

    if status == 'CANCELLED_BEFORE_SHIP':
        return Decision(intent, 'Cancellation confirmed',
                        'This order was cancelled before dispatch. For prepaid orders, payment verification and the applicable refund path require agent review; the four SOP rules do not set an automatic amount here.',
                        'Request payment review', manual_review=True)

    if status == 'DELIVERED':
        return Decision(intent, 'Order marked delivered',
                        'The dataset shows this order as delivered. The four SOP rules do not authorize an automatic refund for every delivered order. For payment, quality, or delivery disputes, request an agent review.',
                        'Request support review', manual_review=True)

    return Decision(intent, 'Support review required',
                    'The available order status does not determine a safe automatic refund under the four SOP rules.',
                    'Request agent review', manual_review=True)


def _float(value):
    try:
        f = float(value)
        return f if f == f else None
    except (TypeError, ValueError):
        return None
