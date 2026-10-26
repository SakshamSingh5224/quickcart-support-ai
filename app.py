"""QuickCart Phase 2E: authenticated, role-scoped Streamlit demo.

No financial operations. Account passwords are hashed in a local SQLite database.
Designed for a portfolio demonstration with synthetic/authorized data ONLY.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from time import time

import pandas as pd
import streamlit as st

from access_control import (
    AccessDenied, agent_queue, authorize_analytics, customer_requests,
    lookup_customer_reference, read_request, request_events, review_request,
    submit_customer_request,
)
from auth_store import AuthError, active_user, authenticate, bootstrap_from_env, init_auth
from conversation import authoritative_turn, optional_local_explanation
from policy_audit import audit_order
from ticket_store import DEFAULT_DB, StoreError, TRANSITIONS, init_db

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
SESSION_TTL_SECONDS = 60 * 60
st.set_page_config(page_title='QuickCart | Secure Demo', page_icon='📦', layout='wide')


@st.cache_data

def load_data():
    return (
        pd.read_csv(DATA / 'orders_clean.csv', dtype={'order_id': str, 'customer_id': str}),
        pd.read_csv(DATA / 'support_tickets_clean.csv',
                    dtype={'ticket_id': str, 'order_id': str, 'customer_id': str}),
    )


@st.cache_resource

def prepare_database():
    init_db(DEFAULT_DB)
    init_auth(DEFAULT_DB)
    bootstrap_from_env(DEFAULT_DB)
    return True


def clear_login():
    for key in ('auth_user_id', 'auth_started_at', 'active_ref', 'turns'):
        st.session_state.pop(key, None)


def signed_in_user():
    uid = st.session_state.get('auth_user_id')
    started = st.session_state.get('auth_started_at', 0)
    if not isinstance(started, (int, float)) or time() - started > SESSION_TTL_SECONDS:
        clear_login()
        return None
    profile = active_user(DEFAULT_DB, uid)
    if profile is None:
        clear_login()
    return profile


try:
    prepare_database()
except (AuthError, OSError, ValueError) as exc:
    st.error('Account configuration is incomplete. Check bootstrap secrets or local account setup.')
    st.caption(type(exc).__name__)
    st.stop()

st.title('📦 QuickCart Order Help')
st.caption('Phase 2E · Local account login · Customer ownership checks · Role-specific tools · Audit history')
st.info('Portfolio demonstration only. No live refunds, replacements, voucher issuance, or courier operations. '
        'For public deployment use ONLY the separate synthetic demo package.')

user = signed_in_user()
if user is None:
    st.subheader('Sign in')
    st.caption('Accounts are provisioned by an administrator. Self-service registration is disabled.')
    with st.form('quickcart_login', clear_on_submit=True):
        username = st.text_input('Username', max_chars=40)
        password = st.text_input('Password', type='password')
        login_clicked = st.form_submit_button('Sign in', type='primary')
    if login_clicked:
        identity = authenticate(DEFAULT_DB, username=username, password=password)
        if identity is None:
            st.error('Invalid credentials or temporarily locked account. Please try later.')
        else:
            clear_login()
            st.session_state['auth_user_id'] = identity['id']
            st.session_state['auth_started_at'] = time()
            st.rerun()
    st.caption('No account yet? Follow PHASE_2E_NOTES.md to create an admin, agent, or customer.')
    st.stop()

with st.sidebar:
    st.markdown(f'**Signed in:** `{user["username"]}`')
    st.caption(f'Role: {user["role"]}')
    if st.button('Sign out'):
        clear_login()
        st.rerun()
    workspaces = {'customer': ['Customer help'],
                  'agent': ['Agent queue'],
                  'admin': ['Agent queue', 'Admin analytics']}[user['role']]
    workspace = st.radio('Workspace', workspaces)
    st.divider()
    allow_llm = user['role'] == 'customer' and os.getenv('QC_PUBLIC_DEMO', '0') != '1'
    use_llm = st.toggle('Optional local Ollama explanation', disabled=not allow_llm, value=False)
    model = st.text_input('Local Ollama model', 'qwen2.5:0.5b',
                          disabled=not allow_llm or not use_llm)
    st.caption('Account session expires after 1 hour; signing out clears chat state.')

try:
    orders, tickets = load_data()
except FileNotFoundError:
    st.error('Cleaned datasets not found. Use your existing local data/ files or the synthetic demo package.')
    st.stop()

if workspace == 'Admin analytics':
    authorize_analytics(user)
    from dashboard_ui import render_admin_dashboard
    render_admin_dashboard(orders, tickets, DEFAULT_DB, user=user)
    st.stop()

if workspace == 'Agent queue':
    st.subheader('Support agent queue')
    st.caption('Role checked; all decisions are administrative follow-up only, NOT financial approvals.')
    states = ['All statuses', 'SUBMITTED', 'IN_REVIEW', 'FOLLOW_UP_APPROVED', 'REJECTED', 'CLOSED']
    status_filter = st.selectbox('Filter requests', states)
    records = agent_queue(user, DEFAULT_DB, status=None if status_filter == 'All statuses' else status_filter)
    if not records:
        st.info('No locally submitted support requests match this status.')
    else:
        st.dataframe(pd.DataFrame([{
            'Request ID': r['request_id'], 'Order': r['order_id'], 'Status': r['status'],
            'Created UTC': r['created_at_utc'], 'Needs reconciliation': bool(r['requires_reconciliation'])
        } for r in records]), hide_index=True, use_container_width=True)
        selected_id = st.selectbox('Select request', [r['request_id'] for r in records])
        record = read_request(user, orders, DEFAULT_DB, selected_id)
        st.write('**Order:**', record['order_id'], '| **Historical ticket:**', record['source_ticket_id'] or 'None')
        st.write('**Customer question:**', record['customer_question'])
        st.write('**Policy decision:**', record['policy_headline'])
        st.write('**Suggested action:**', record['suggested_action'])
        st.write('**Status:**', record['status'])
        if record['requires_reconciliation']:
            st.warning('Historical refund/replacement records require reconciliation.')
        st.markdown('#### Audit history')
        st.dataframe(pd.DataFrame([{
            'UTC': e['event_time_utc'], 'From': e['previous_status'] or '—',
            'To': e['new_status'], 'Actor': e['actor'], 'Note': e['note']
        } for e in request_events(user, orders, DEFAULT_DB, selected_id)]),
            hide_index=True, use_container_width=True)
        possible = TRANSITIONS[record['status']]
        if possible:
            with st.form(f'review_{selected_id}_{record["status"]}'):
                target = st.selectbox('Next administrative status', list(possible))
                st.caption(f'Reviewer identity: {user["username"]} (from signed-in account)')
                note = st.text_area('Reason for status change', max_chars=1000)
                update = st.form_submit_button('Save status change')
            if update:
                try:
                    review_request(user, DEFAULT_DB, request_id=selected_id,
                                   expected_status=record['status'], new_status=target, note=note)
                    st.rerun()
                except StoreError as exc:
                    st.error(str(exc))
        else:
            st.info('Request is closed; no further transitions are available.')
    st.stop()

# Customer help. All order lookups pass through ownership checks first.
with st.form('customer_order_form'):
    reference = st.text_input('Your order ID or historical ticket ID', placeholder='ORD-700002')
    selected = st.form_submit_button('Load order', type='primary')
if selected:
    candidate = reference.strip().upper()
    try:
        lookup_customer_reference(user, orders, tickets, candidate)
    except AccessDenied:
        st.error('Order or ticket not found for your account.')
    else:
        if candidate != st.session_state.get('active_ref'):
            st.session_state['turns'] = []
        st.session_state['active_ref'] = candidate

ref = st.session_state.get('active_ref')
if not ref:
    st.info('Enter an order or historical ticket linked to your customer account.')
    st.stop()
try:
    order, matched_ticket, history = lookup_customer_reference(user, orders, tickets, ref)
except AccessDenied:
    st.session_state.pop('active_ref', None)
    st.session_state.pop('turns', None)
    st.error('Order or ticket not found for your account.')
    st.stop()

order_id = order['order_id']
audit = audit_order(order, history)
st.subheader('Order found')
a, b = st.columns(2)
a.metric('Order ID', order_id)
b.metric('Delivery status', str(order.get('delivery_status', '')).replace('_', ' ').title())
st.write('**Courier:**', order.get('courier_partner', 'Unavailable'))
st.write('**Payment:**', order.get('payment_method', 'Unavailable'))
st.write('**Order value:**', f'₹{float(order["order_amount"]):,.2f}'
         if pd.notna(order.get('order_amount')) else 'Unavailable')
if matched_ticket:
    st.write('**Latest/matched historical ticket:**', matched_ticket['ticket_id'], '—', matched_ticket['resolution_status'])
if audit['flags']:
    with st.expander(f'Historical policy flags ({len(audit["flags"])})', expanded=True):
        for ticket_id, flag in audit['flags']:
            st.warning(f'{ticket_id} / {flag.rule}: {flag.explanation}')
if audit['requires_reconciliation']:
    st.info('Existing refund/replacement records require agent reconciliation first.')

previous = customer_requests(user, orders, DEFAULT_DB, order_id=order_id)
with st.expander(f'Local support requests for this order ({len(previous)})'):
    if previous:
        st.dataframe(pd.DataFrame([{
            'Request ID': r['request_id'], 'Status': r['status'],
            'Action': r['suggested_action'], 'Created UTC': r['created_at_utc']
        } for r in previous]), hide_index=True, use_container_width=True)
    else:
        st.caption('No local requests yet.')

st.subheader('Chat with support')
turns = st.session_state.setdefault('turns', [])
for turn in turns:
    with st.chat_message('user'):
        st.write(turn['user'])
    with st.chat_message('assistant'):
        st.markdown('**' + turn['headline'] + '**')
        st.write(turn['answer'].split('\n\n', 1)[-1])
        if turn.get('ai_explanation'):
            st.caption('Optional model wording (not a policy decision): ' + turn['ai_explanation'])
        if turn.get('submitted_request_id'):
            st.caption('Local request: ' + turn['submitted_request_id'])

question = st.chat_input('Ask about delivery, damage, refund eligibility or next steps…')
if question:
    if len(question) > 1200:
        st.error('Keep messages to 1,200 characters or fewer.')
    else:
        turn = authoritative_turn(order, question, matched_ticket, history, turns)
        turn['submission_token'] = uuid.uuid4().hex
        if use_llm:
            extra, error = optional_local_explanation(order, turn, model)
            if extra:
                turn['ai_explanation'] = extra
            elif error:
                st.caption(error)
        turns.append(turn)
        st.rerun()

if turns:
    latest = turns[-1]
    latest.setdefault('submission_token', uuid.uuid4().hex)
    st.subheader('Instant next step — saved support request')
    st.write('Recommended action: **' + latest['action'] + '**')
    if latest.get('submitted_request_id'):
        try:
            record = read_request(user, orders, DEFAULT_DB, latest['submitted_request_id'])
        except AccessDenied:
            st.error('Request no longer available for your account.')
        else:
            st.success(f'Request {record["request_id"]} stored locally. Status: {record["status"]}.')
            st.download_button('Download request receipt (JSON)',
                               json.dumps(record, indent=2, ensure_ascii=False),
                               file_name=f'{record["request_id"]}.json', mime='application/json')
    elif st.button('Submit local support request', type='primary'):
        try:
            created = submit_customer_request(
                user, orders, DEFAULT_DB, order_id=order_id,
                token=latest['submission_token'],
                source_ticket_id=matched_ticket['ticket_id'] if matched_ticket else None,
                customer_question=latest['user'], turn=latest, audit=audit, tickets=tickets)
            latest['submitted_request_id'] = created['request_id']
            st.rerun()
        except (AccessDenied, StoreError) as exc:
            st.error(str(exc))
    if st.button('Clear conversation'):
        st.session_state['turns'] = []
        st.rerun()

st.caption('Only the Python SOP rules determine financial guidance. Local approvals never execute payments.')
