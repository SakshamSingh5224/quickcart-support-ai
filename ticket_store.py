"""Phase 2C: local SQLite persistence for DEMO support requests.

No payment or courier operations. Access checks are enforced through access_control.py.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / 'instance' / 'quickcart.sqlite3'
STATES = ('SUBMITTED', 'IN_REVIEW', 'FOLLOW_UP_APPROVED', 'REJECTED', 'CLOSED')
TRANSITIONS = {
    'SUBMITTED': ('IN_REVIEW', 'REJECTED'),
    'IN_REVIEW': ('FOLLOW_UP_APPROVED', 'REJECTED'),
    'FOLLOW_UP_APPROVED': ('CLOSED',),
    'REJECTED': ('CLOSED',),
    'CLOSED': (),
}

class StoreError(ValueError):
    """Invalid input, invalid transition, or stale request version."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connection(db_path=DEFAULT_DB):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path=DEFAULT_DB):
    """Safe to repeat on every app startup, with an explicit v1 schema."""
    with connection(db_path) as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS support_requests (
                request_id TEXT PRIMARY KEY,
                submission_token TEXT NOT NULL UNIQUE,
                order_id TEXT NOT NULL,
                source_ticket_id TEXT,
                customer_question TEXT NOT NULL,
                policy_headline TEXT NOT NULL,
                suggested_action TEXT NOT NULL,
                eligible_refund_inr REAL,
                voucher_inr REAL NOT NULL DEFAULT 0,
                historical_refunds_inr REAL NOT NULL DEFAULT 0,
                requires_manual_review INTEGER NOT NULL CHECK (requires_manual_review IN (0,1)),
                requires_reconciliation INTEGER NOT NULL CHECK (requires_reconciliation IN (0,1)),
                status TEXT NOT NULL DEFAULT 'SUBMITTED'
                    CHECK (status IN ('SUBMITTED','IN_REVIEW','FOLLOW_UP_APPROVED','REJECTED','CLOSED')),
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                last_reviewer TEXT,
                last_review_note TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_requests_order ON support_requests(order_id, created_at_utc);
            CREATE INDEX IF NOT EXISTS idx_requests_status ON support_requests(status, created_at_utc);
            CREATE TABLE IF NOT EXISTS request_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL REFERENCES support_requests(request_id),
                event_time_utc TEXT NOT NULL,
                previous_status TEXT,
                new_status TEXT NOT NULL,
                actor TEXT NOT NULL,
                note TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_request ON request_events(request_id, event_id);
        ''')


def _text(value, name, limit, *, required=True):
    if not isinstance(value, str):
        raise StoreError(f'{name} must be text.')
    cleaned = value.strip()
    if len(cleaned) > limit or (required and not cleaned):
        raise StoreError(f'{name} must contain 1–{limit} characters.' if required else f'{name} exceeds {limit} characters.')
    return cleaned


def _amount(value, name, *, allow_none=False):
    if value is None and allow_none:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        raise StoreError(f'{name} must be a valid non-negative number.') from None
    if not isfinite(n) or n < 0 or n > 10**9:
        raise StoreError(f'{name} must be a finite, non-negative number.')
    return round(n, 2)


def _validate_request(*, token, order_id, source_ticket_id, customer_question, turn, audit):
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
        raise StoreError('Submission token must be a UUID hex value.')
    order_id = _text(order_id, 'Order ID', 40)
    if not re.fullmatch(r'ORD-\d+', order_id):
        raise StoreError('Order ID has an invalid format.')
    if source_ticket_id is not None:
        source_ticket_id = _text(source_ticket_id, 'Source ticket ID', 40)
        if not re.fullmatch(r'TKT-\d+', source_ticket_id):
            raise StoreError('Source ticket ID has an invalid format.')
    question = _text(customer_question, 'Question', 1200)
    if not isinstance(turn, dict) or not isinstance(audit, dict):
        raise StoreError('Policy decision and historical audit are required.')
    headline = _text(turn.get('headline'), 'Policy headline', 250)
    action = _text(turn.get('action'), 'Suggested action', 250)
    eligible = _amount(turn.get('eligible_refund'), 'Eligible refund', allow_none=True)
    voucher = _amount(turn.get('voucher', 0), 'Voucher')
    historical = _amount(audit.get('recorded_refunds_inr', 0), 'Historical refunds')
    requires_reconciliation = bool(audit.get('requires_reconciliation', False))
    requires_review = bool(turn.get('manual_review', False)) or requires_reconciliation
    # Do not accept new monetary recommendations while history needs reconciliation.
    if requires_reconciliation and ((eligible is not None and eligible > 0) or voucher > 0):
        raise StoreError('Financial suggestions must be suppressed pending historical reconciliation.')
    return (token, order_id, source_ticket_id, question, headline, action, eligible,
            voucher, historical, int(requires_review), int(requires_reconciliation))


def create_request(db_path=DEFAULT_DB, *, token, order_id, source_ticket_id=None,
                   customer_question, turn, audit, actor="customer-demo"):
    """Insert one SUBMITTED request; repeat submissions with the same token are idempotent.

    A matching token cannot be reused with different payload. No external ticket is created.
    """
    actor = _text(actor, "Request actor", 80)
    fields = _validate_request(token=token, order_id=order_id,
                               source_ticket_id=source_ticket_id,
                               customer_question=customer_question, turn=turn, audit=audit)
    with connection(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT * FROM support_requests WHERE submission_token=?', (token,)).fetchone()
        if existing:
            keys = ('submission_token', 'order_id', 'source_ticket_id', 'customer_question',
                    'policy_headline', 'suggested_action', 'eligible_refund_inr', 'voucher_inr',
                    'historical_refunds_inr', 'requires_manual_review', 'requires_reconciliation')
            if tuple(existing[k] for k in keys) != fields:
                raise StoreError('Submission token already belongs to a different request.')
            return dict(existing)
        request_id = 'QC-' + uuid.uuid4().hex[:16].upper()
        now = utc_now()
        db.execute('''
            INSERT INTO support_requests (
              request_id, submission_token, order_id, source_ticket_id, customer_question,
              policy_headline, suggested_action, eligible_refund_inr, voucher_inr,
              historical_refunds_inr, requires_manual_review, requires_reconciliation,
              status, created_at_utc, updated_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (request_id, *fields, 'SUBMITTED', now, now))
        db.execute('''INSERT INTO request_events
                   (request_id,event_time_utc,previous_status,new_status,actor,note)
                   VALUES (?,?,?,?,?,?)''',
                   (request_id, now, None, 'SUBMITTED', actor, 'Local request submitted; no external action.'))
        return dict(db.execute('SELECT * FROM support_requests WHERE request_id=?', (request_id,)).fetchone())


def get_request(db_path, request_id):
    with connection(db_path) as db:
        row = db.execute('SELECT * FROM support_requests WHERE request_id=?', (request_id,)).fetchone()
        return dict(row) if row else None


def list_requests(db_path=DEFAULT_DB, *, status=None, order_id=None, limit=200):
    if status is not None and status not in STATES:
        raise StoreError('Invalid status filter.')
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise StoreError('Invalid limit.')
    where, args = [], []
    if status:
        where.append('status=?')
        args.append(status)
    if order_id:
        where.append('order_id=?')
        args.append(order_id)
    sql = 'SELECT * FROM support_requests'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY created_at_utc DESC, request_id DESC LIMIT ?'
    args.append(limit)
    with connection(db_path) as db:
        return [dict(row) for row in db.execute(sql, args).fetchall()]


def list_events(db_path, request_id):
    with connection(db_path) as db:
        return [dict(row) for row in db.execute(
            'SELECT * FROM request_events WHERE request_id=? ORDER BY event_id', (request_id,)).fetchall()]


def update_request_status(db_path, *, request_id, expected_status, new_status, reviewer, note):
    """Only administrative queue transitions; NOT refund/replacement authorization.

    Uses atomic expected-status comparison and writes an audit event in the same transaction.
    """
    reviewer = _text(reviewer, 'Reviewer label', 80)
    note = _text(note, 'Review note', 1000)
    if new_status not in STATES or expected_status not in STATES:
        raise StoreError('Unknown request status.')
    if new_status not in TRANSITIONS[expected_status]:
        raise StoreError(f'Invalid transition: {expected_status} → {new_status}.')
    with connection(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT status FROM support_requests WHERE request_id=?', (request_id,)).fetchone()
        if current is None:
            raise StoreError('Request not found.')
        if current['status'] != expected_status:
            raise StoreError(f'Stale state: request is now {current["status"]}; refresh and try again.')
        now = utc_now()
        result = db.execute('''UPDATE support_requests SET status=?, updated_at_utc=?,
                               last_reviewer=?, last_review_note=?
                               WHERE request_id=? AND status=?''',
                            (new_status, now, reviewer, note, request_id, expected_status))
        if result.rowcount != 1:
            raise StoreError('Concurrent update; refresh and retry.')
        db.execute('''INSERT INTO request_events
                   (request_id,event_time_utc,previous_status,new_status,actor,note)
                   VALUES (?,?,?,?,?,?)''',
                   (request_id, now, expected_status, new_status, reviewer, note))
        return dict(db.execute('SELECT * FROM support_requests WHERE request_id=?', (request_id,)).fetchone())
