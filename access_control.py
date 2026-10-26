"""Centralized role and ownership checks around Phase 2C ticket operations."""
from __future__ import annotations
import re

from ticket_store import (DEFAULT_DB, StoreError, create_request, get_request,
                          list_events, list_requests, update_request_status)

class AccessDenied(PermissionError):
    pass


def require_role(user, *allowed):
    if not isinstance(user, dict) or user.get('role') not in allowed or not user.get('username'):
        raise AccessDenied('You are not authorized for this action.')


def customer_order(user, orders, order_id):
    require_role(user, 'customer')
    if not re.fullmatch(r'ORD-\d+', str(order_id)):
        raise AccessDenied('Order not found or not authorized.')
    rows = orders.loc[(orders['order_id'] == order_id) &
                      (orders['customer_id'] == user.get('customer_id'))]
    if rows.empty:
        raise AccessDenied('Order not found or not authorized.')
    return rows.iloc[0].to_dict()


def lookup_customer_reference(user, orders, tickets, ref):
    """Check ownership before revealing order details or a historical ticket."""
    require_role(user, 'customer')
    if not isinstance(ref, str) or not re.fullmatch(r'(ORD-\d+|TKT-\d+)', ref):
        raise AccessDenied('Order not found or not authorized.')
    matched_ticket = None
    if ref.startswith('TKT-'):
        matches = tickets.loc[(tickets['ticket_id'] == ref) &
                              (tickets['customer_id'] == user.get('customer_id'))]
        if matches.empty:
            raise AccessDenied('Order not found or not authorized.')
        matched_ticket = matches.iloc[0].to_dict()
        order_id = str(matched_ticket['order_id'])
    else:
        order_id = ref
    order = customer_order(user, orders, order_id)
    history = tickets.loc[(tickets['order_id'] == order_id) &
                          (tickets['customer_id'] == user.get('customer_id'))]
    history = history.sort_values('ticket_created_at', ascending=False)
    if matched_ticket is None and not history.empty:
        matched_ticket = history.iloc[0].to_dict()
    return order, matched_ticket, history.to_dict('records')


def customer_requests(user, orders, db_path=DEFAULT_DB, *, order_id):
    customer_order(user, orders, order_id)
    return list_requests(db_path, order_id=order_id, limit=100)


def submit_customer_request(user, orders, db_path=DEFAULT_DB, *, order_id, token,
                            source_ticket_id, customer_question, turn, audit, tickets=None):
    customer_order(user, orders, order_id)
    if source_ticket_id is not None:
        if tickets is None:
            raise AccessDenied('Historical ticket ownership data is required.')
        matches = tickets.loc[(tickets['ticket_id'] == source_ticket_id) &
                              (tickets['customer_id'] == user.get('customer_id')) &
                              (tickets['order_id'] == order_id)]
        if matches.empty:
            raise AccessDenied('Historical ticket not found or not authorized.')
    return create_request(db_path, token=token, order_id=order_id,
                          source_ticket_id=source_ticket_id, customer_question=customer_question,
                          turn=turn, audit=audit, actor=user['username'])


def read_request(user, orders, db_path, request_id):
    require_role(user, 'customer', 'agent', 'admin')
    record = get_request(db_path, request_id)
    if record is None:
        raise AccessDenied('Request not found or not authorized.')
    if user['role'] == 'customer':
        customer_order(user, orders, record['order_id'])
    return record


def agent_queue(user, db_path=DEFAULT_DB, *, status=None):
    require_role(user, 'agent', 'admin')
    return list_requests(db_path, status=status)


def request_events(user, orders, db_path, request_id):
    read_request(user, orders, db_path, request_id)
    return list_events(db_path, request_id)


def review_request(user, db_path=DEFAULT_DB, *, request_id, expected_status, new_status, note):
    require_role(user, 'agent', 'admin')
    return update_request_status(db_path, request_id=request_id, expected_status=expected_status,
                                 new_status=new_status, reviewer=user['username'], note=note)


def authorize_analytics(user):
    require_role(user, 'admin')
    return True
