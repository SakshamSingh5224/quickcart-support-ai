import pytest
from policy_audit import audit_order, audit_ticket
from policy_engine import decide


def order(status='DELIVERED', amount=799, payment='UPI'):
    return dict(delivery_status=status, order_amount=amount, payment_method=payment)


def ticket(refund=0, resolution='Resolved - Full Refund Issued', issue='Other', ticket_id='TKT-1'):
    return dict(ticket_id=ticket_id, refund_amount=refund, resolution_status=resolution, issue_category=issue)


def test_replacement_plus_cash():
    assert 'R2' in [f.rule for f in audit_ticket(order(), ticket(799, 'Resolved - Replacement Sent'))]


def test_cod_cancelled_refund():
    assert 'R3' in [f.rule for f in audit_ticket(order('CANCELLED_BEFORE_SHIP', payment='Cash on Delivery (COD)'), ticket(10))]


@pytest.mark.parametrize('refund,expected', [(899, False), (899.01, False), (899.02, True), (1000, True)])
def test_refund_cap_rounding(refund, expected):
    assert ('R4' in [f.rule for f in audit_ticket(order(), ticket(refund))]) == expected


def test_delayed_full_cash_refund():
    assert 'R1' in [f.rule for f in audit_ticket(order('DELAYED_IN_TRANSIT'), ticket(799))]


def test_damage_invalid_partial_cash():
    assert 'R2' in [f.rule for f in audit_ticket(order(), ticket(200, issue='Damaged / Defective Item Received'))]


def test_multi_ticket_reconciliation_blocks_new_refund():
    history = [ticket(400, ticket_id='TKT-1'), ticket(399, ticket_id='TKT-2')]
    result = audit_order(order(), history)
    assert result['recorded_refunds_inr'] == 799
    assert result['requires_reconciliation']
    d = decide(order('LOST_IN_TRANSIT'), 'refund', all_tickets=history)
    assert d.eligible_refund is None and d.manual_review


def test_historical_replacement_blocks_new_replacement_or_refund():
    d = decide(order(), 'my item is broken', all_tickets=[ticket(0, 'Resolved - Replacement Sent')])
    assert d.manual_review and d.eligible_refund is None


def test_no_history_lost_is_eligible():
    assert decide(order('LOST_IN_TRANSIT'), 'refund', all_tickets=[]).eligible_refund == 799


def test_nan_and_infinity_amount_require_review():
    for value in (float('nan'), float('inf'), None):
        assert decide(order(amount=value), 'refund').manual_review
