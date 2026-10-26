"""Phase 2C regression tests: local SQLite, workflows, audit & safe boundaries."""
import sqlite3
import uuid
import pytest

from ticket_store import (
    DEFAULT_DB, TRANSITIONS, StoreError, create_request, get_request, init_db,
    list_events, list_requests, update_request_status,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / 'subdirectory' / 'support.sqlite3'
    init_db(path)
    return path


@pytest.fixture
def payload():
    return {
        'token': uuid.uuid4().hex,
        'order_id': 'ORD-700002',
        'source_ticket_id': 'TKT-900002',
        'customer_question': 'My item is broken. Can I get a refund?',
        'turn': {
            'headline': 'Existing support history — agent review required',
            'action': 'Request historical resolution review',
            'eligible_refund': None,
            'voucher': 0,
            'manual_review': True,
        },
        'audit': {'requires_reconciliation': True, 'recorded_refunds_inr': 799},
    }


def test_initialization_reentrant(db):
    init_db(db)
    assert db.exists()
    assert list_requests(db) == []


def test_create_and_read_persists_across_connections(db, payload):
    rec = create_request(db, **payload)
    assert rec['request_id'].startswith('QC-')
    assert rec['status'] == 'SUBMITTED'
    assert rec['order_id'] == 'ORD-700002'
    assert rec['requires_manual_review'] == 1
    assert rec['requires_reconciliation'] == 1
    assert rec['historical_refunds_inr'] == 799
    assert get_request(db, rec['request_id']) == rec
    assert list_requests(db, order_id='ORD-700002')[0]['request_id'] == rec['request_id']
    assert list_requests(db, order_id='ORD-700003') == []
    assert list_requests(db, status='IN_REVIEW') == []
    events = list_events(db, rec['request_id'])
    assert len(events) == 1 and events[0]['new_status'] == 'SUBMITTED'
    assert events[0]['previous_status'] is None


def test_double_submit_is_idempotent(db, payload):
    first = create_request(db, **payload)
    second = create_request(db, **payload)
    assert first['request_id'] == second['request_id']
    assert len(list_requests(db)) == 1
    assert len(list_events(db, first['request_id'])) == 1


def test_same_token_different_request_rejected(db, payload):
    create_request(db, **payload)
    altered = {**payload, 'customer_question': 'Different question'}
    with pytest.raises(StoreError, match='different request'):
        create_request(db, **altered)
    assert len(list_requests(db)) == 1


def test_expected_lifecycle_and_audit(db, payload):
    request = create_request(db, **payload)
    request_id = request['request_id']
    for previous, target in [('SUBMITTED', 'IN_REVIEW'), ('IN_REVIEW', 'FOLLOW_UP_APPROVED'),
                             ('FOLLOW_UP_APPROVED', 'CLOSED')]:
        updated = update_request_status(db, request_id=request_id, expected_status=previous,
                                        new_status=target, reviewer='demo-agent', note='Reviewed historical records')
        assert updated['status'] == target
    assert [e['new_status'] for e in list_events(db, request_id)] == [
        'SUBMITTED', 'IN_REVIEW', 'FOLLOW_UP_APPROVED', 'CLOSED'
    ]
    assert list_requests(db, status='CLOSED')[0]['request_id'] == request_id
    assert 'PAID' not in TRANSITIONS


def test_rejection_path(db, payload):
    request_id = create_request(db, **payload)['request_id']
    assert update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                                 new_status='REJECTED', reviewer='qa', note='Not eligible')['status'] == 'REJECTED'
    assert update_request_status(db, request_id=request_id, expected_status='REJECTED',
                                 new_status='CLOSED', reviewer='qa', note='Administrative closure')['status'] == 'CLOSED'


@pytest.mark.parametrize('start,target', [
    ('SUBMITTED','CLOSED'), ('SUBMITTED','FOLLOW_UP_APPROVED'), ('IN_REVIEW','SUBMITTED'),
    ('REJECTED','IN_REVIEW'), ('CLOSED','IN_REVIEW'), ('SUBMITTED','SUBMITTED'),
])
def test_invalid_transitions_rejected(db, payload, start, target):
    request_id = create_request(db, **payload)['request_id']
    if start == 'IN_REVIEW':
        update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                              new_status='IN_REVIEW', reviewer='qa', note='Investigating')
    if start == 'REJECTED':
        update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                              new_status='REJECTED', reviewer='qa', note='Denied')
    if start == 'CLOSED':
        update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                              new_status='REJECTED', reviewer='qa', note='Denied')
        update_request_status(db, request_id=request_id, expected_status='REJECTED',
                              new_status='CLOSED', reviewer='qa', note='Done')
    before = len(list_events(db, request_id))
    with pytest.raises(StoreError, match='Invalid transition'):
        update_request_status(db, request_id=request_id, expected_status=start,
                              new_status=target, reviewer='qa', note='invalid')
    assert len(list_events(db, request_id)) == before


def test_stale_update_detected_without_mutation(db, payload):
    request_id = create_request(db, **payload)['request_id']
    update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                          new_status='IN_REVIEW', reviewer='qa', note='Checking')
    with pytest.raises(StoreError, match='Stale state'):
        update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                              new_status='REJECTED', reviewer='other-agent', note='Deny')
    assert get_request(db, request_id)['status'] == 'IN_REVIEW'
    assert len(list_events(db, request_id)) == 2


def test_missing_notes_and_reviewer_rejected(db, payload):
    request_id = create_request(db, **payload)['request_id']
    for reviewer, note in [('', 'Reviewed'), ('agent', ''), ('agent', 'a' * 1001)]:
        with pytest.raises(StoreError):
            update_request_status(db, request_id=request_id, expected_status='SUBMITTED',
                                  new_status='IN_REVIEW', reviewer=reviewer, note=note)
    assert get_request(db, request_id)['status'] == 'SUBMITTED'


def test_unknown_request_rejected(db):
    with pytest.raises(StoreError, match='not found'):
        update_request_status(db, request_id='QC-NONEXISTENT', expected_status='SUBMITTED',
                              new_status='IN_REVIEW', reviewer='qa', note='Review')
    assert get_request(db, 'QC-NONEXISTENT') is None


@pytest.mark.parametrize('invalid', [
    {'token': 'not-a-uuid'},
    {'order_id': 'ORD-ABC'},
    {'source_ticket_id': 'TKT-BAD'},
    {'customer_question': ''},
    {'customer_question': 'x' * 1201},
    {'turn': {'headline': 'Title', 'action': 'Review', 'eligible_refund': float('nan'), 'voucher': 0}},
    {'turn': {'headline': 'Title', 'action': 'Review', 'eligible_refund': 0, 'voucher': -100}},
])
def test_bad_submissions_rejected(db, payload, invalid):
    with pytest.raises(StoreError):
        create_request(db, **{**payload, **invalid})
    assert list_requests(db) == []


def test_reconciliation_rejects_financial_suggestion(db, payload):
    turn = {**payload['turn'], 'eligible_refund': 799, 'voucher': 100}
    with pytest.raises(StoreError, match='suppressed'):
        create_request(db, **{**payload, 'turn': turn})


def test_nonreconciliation_eligibility_is_guidance_only(db, payload):
    altered = {**payload, 'audit': {'requires_reconciliation': False, 'recorded_refunds_inr': 0},
               'turn': {**payload['turn'], 'eligible_refund': 799, 'voucher': 0}}
    rec = create_request(db, **altered)
    assert rec['eligible_refund_inr'] == 799
    assert rec['status'] == 'SUBMITTED'
    with sqlite3.connect(db) as conn:
        cols = [c[1] for c in conn.execute('PRAGMA table_info(support_requests)')]
    assert 'payment_transaction_id' not in cols


def test_sql_text_is_data_not_commands(db, payload):
    malicious = "Why?'); DELETE FROM support_requests; --"
    rec = create_request(db, **{**payload, 'customer_question': malicious})
    assert get_request(db, rec['request_id'])['customer_question'] == malicious
    assert len(list_requests(db)) == 1


def test_status_filter_and_limit_validation(db):
    with pytest.raises(StoreError):
        list_requests(db, status='PAID')
    with pytest.raises(StoreError):
        list_requests(db, limit=0)
