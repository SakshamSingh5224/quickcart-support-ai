import pytest
"""Real cleaned-dataset integration smoke test for Phase 2C."""
from pathlib import Path
import uuid
import pandas as pd
from conversation import authoritative_turn
from policy_audit import audit_order
from ticket_store import init_db, create_request, list_requests, update_request_status, list_events

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.original_dataset
def test_historical_conflict_yields_persisted_review_request(tmp_path):
    orders = pd.read_csv(ROOT / 'data' / 'orders_clean.csv')
    tickets = pd.read_csv(ROOT / 'data' / 'support_tickets_clean.csv')
    order = orders.loc[orders.order_id == 'ORD-700002'].iloc[0].to_dict()
    history = tickets.loc[tickets.order_id == 'ORD-700002'].to_dict('records')
    audit = audit_order(order, history)
    turn = authoritative_turn(order, 'My item is broken, can I get a refund?', history[0], history, [])
    assert audit['requires_reconciliation'] is True
    assert audit['recorded_refunds_inr'] == 799
    assert turn['eligible_refund'] is None
    assert turn['voucher'] == 0
    assert turn['action'] == 'Request historical resolution review'

    db = tmp_path / 'app.sqlite3'
    init_db(db)
    record = create_request(db, token=uuid.uuid4().hex, order_id=order['order_id'],
                            source_ticket_id=history[0]['ticket_id'],
                            customer_question=turn['user'], turn=turn, audit=audit)
    assert record['status'] == 'SUBMITTED'
    assert record['requires_reconciliation'] == 1
    assert len(list_requests(db, order_id='ORD-700002')) == 1
    reviewed = update_request_status(db, request_id=record['request_id'], expected_status='SUBMITTED',
                                     new_status='IN_REVIEW', reviewer='demo-agent',
                                     note='Replacement and recorded refund require investigation')
    assert reviewed['status'] == 'IN_REVIEW'
    assert [x['new_status'] for x in list_events(db, record['request_id'])] == ['SUBMITTED', 'IN_REVIEW']
