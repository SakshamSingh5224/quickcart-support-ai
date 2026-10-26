import pytest
"""Regression test against the provided cleaned Part 1 dataset."""
import csv
from pathlib import Path
from policy_audit import audit_order
from policy_engine import decide

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.original_dataset
def test_known_replacement_plus_refund_from_dataset():
    with (ROOT / 'data' / 'orders_clean.csv').open(newline='', encoding='utf-8') as handle:
        order = next(r for r in csv.DictReader(handle) if r['order_id'] == 'ORD-700002')
    with (ROOT / 'data' / 'support_tickets_clean.csv').open(newline='', encoding='utf-8') as handle:
        tickets = [r for r in csv.DictReader(handle) if r['order_id'] == 'ORD-700002']
    audit = audit_order(order, tickets)
    assert any(flag.rule == 'R2' for _, flag in audit['flags'])
    assert audit['recorded_refunds_inr'] >= 799
    decision = decide(order, 'My item is broken, please refund', tickets[0], tickets)
    assert decision.eligible_refund is None and decision.manual_review
