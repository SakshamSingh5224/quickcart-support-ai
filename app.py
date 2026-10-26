"""QuickCart Phase 2C: local customer chat + persistent support-ticket workflow.

WARNING: neither the customer screen nor the demo agent console authenticates people.
Keep this app on localhost with approved/synthetic CSVs; no payment integrations exist.
"""
import json
import re
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
from conversation import authoritative_turn, optional_local_explanation
from policy_audit import audit_order
from ticket_store import (
    DEFAULT_DB, StoreError, TRANSITIONS, create_request, get_request, init_db,
    list_events, list_requests, update_request_status,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
st.set_page_config(page_title='QuickCart | Order Help', page_icon='📦', layout='centered')


@st.cache_data
def load_data():
    return (pd.read_csv(DATA / 'orders_clean.csv', dtype={'order_id': str, 'customer_id': str}),
            pd.read_csv(DATA / 'support_tickets_clean.csv',
                        dtype={'ticket_id': str, 'order_id': str, 'customer_id': str}))


@st.cache_resource
def prepare_database():
    init_db(DEFAULT_DB)
    return True


prepare_database()
orders, tickets = load_data()
st.title('📦 QuickCart Order Help')
st.caption('Phase 2C · Conversational policy support · SQLite ticket tracking · Local agent review')
st.warning('LOCAL DEMO ONLY — No identity verification or role authorization. Do not deploy with real customer data. '
           'No refunds, replacements, vouchers, courier changes, or external support tickets are executed.')

with st.sidebar:
    workspace = st.radio('Workspace (demo only)', ['Customer help', 'Agent queue'], index=0,
                         help='Switching to Agent queue does not authenticate a reviewer.')
    st.divider()
    use_llm = st.toggle('Optional local Ollama explanations', value=False, disabled=workspace != 'Customer help',
                        help='Localhost-only, supplemental wording; not used to make refund decisions.')
    model = st.text_input('Installed Ollama model', value='qwen2.5:0.5b',
                          disabled=not use_llm or workspace != 'Customer help')
    st.caption('Data: cleaned CSV snapshot. New demo requests: instance/quickcart.sqlite3 (not committed to Git).')

if workspace == 'Agent queue':
    st.subheader('Local support review queue')
    st.error('This agent screen has NO login or access control. It is for a local demonstration only.')
    st.caption('FOLLOW_UP_APPROVED means an agent approved administrative follow-up. '
               'It does NOT approve or execute a cash refund, voucher, or replacement.')
    filter_value = st.selectbox('Filter requests', ['All statuses', 'SUBMITTED', 'IN_REVIEW',
                                                   'FOLLOW_UP_APPROVED', 'REJECTED', 'CLOSED'])
    records = list_requests(DEFAULT_DB, status=None if filter_value == 'All statuses' else filter_value)
    if not records:
        st.info('No requests match this filter. Submit a request from Customer help first.')
    else:
        st.dataframe(pd.DataFrame([{
            'Request ID': item['request_id'], 'Order': item['order_id'],
            'Status': item['status'], 'Created (UTC)': item['created_at_utc'],
            'Needs reconciliation': bool(item['requires_reconciliation']),
        } for item in records]), hide_index=True, use_container_width=True)
        selected_id = st.selectbox('Select request', [r['request_id'] for r in records])
        record = get_request(DEFAULT_DB, selected_id)
        if record is not None:
            st.write('**Order:**', record['order_id'], '| **Historical ticket:**', record['source_ticket_id'] or 'None')
            st.write('**Question:**', record['customer_question'])
            st.write('**Policy decision:**', record['policy_headline'])
            st.write('**Suggested action:**', record['suggested_action'])
            st.write('**Status:**', record['status'])
            st.write('**Historical refund total:** ₹{:,.2f}'.format(record['historical_refunds_inr']))
            if record['requires_reconciliation']:
                st.warning('Historical refund/replacement reconciliation is required. '
                           'This queue cannot bypass the financial policy engine.')
            st.markdown('#### Audit history')
            events = list_events(DEFAULT_DB, selected_id)
            st.dataframe(pd.DataFrame([{
                'UTC': e['event_time_utc'], 'From': e['previous_status'] or '—',
                'To': e['new_status'], 'Reviewer (demo label)': e['actor'], 'Note': e['note'],
            } for e in events]), hide_index=True, use_container_width=True)
            allowed = TRANSITIONS[record['status']]
            if allowed:
                st.markdown('#### Update administrative status')
                with st.form(f'review_form_{selected_id}_{record["status"]}'):
                    target_status = st.selectbox('Next status', list(allowed))
                    reviewer = st.text_input('Reviewer label (NOT verified identity)', value='demo-agent')
                    note = st.text_area('Review note (required)', max_chars=1000,
                                        placeholder='Explain why the status should change...')
                    update_clicked = st.form_submit_button('Save status change', type='primary')
                if update_clicked:
                    try:
                        update_request_status(DEFAULT_DB, request_id=selected_id,
                                              expected_status=record['status'],
                                              new_status=target_status, reviewer=reviewer, note=note)
                        st.rerun()
                    except StoreError as exc:
                        st.error(str(exc))
            else:
                st.info('This request is closed. No further transitions are permitted.')
    st.stop()

# Customer workspace — historical CSV lookup is read-only.
with st.form('order_lookup_form'):
    reference = st.text_input('Order ID or historical ticket ID', placeholder='ORD-700002')
    submitted = st.form_submit_button('Load order', type='primary')

if submitted:
    ref = reference.strip().upper()
    if not re.fullmatch(r'(ORD-\d+|TKT-\d+)', ref):
        st.error('Use a valid ID such as ORD-700002 or TKT-900002.')
    else:
        if ref != st.session_state.get('active_ref'):
            st.session_state['turns'] = []
        st.session_state['active_ref'] = ref

ref = st.session_state.get('active_ref')
if not ref:
    st.info('Load an order, chat, and submit a locally tracked support request.')
    st.stop()

matched_ticket = None
if ref.startswith('TKT-'):
    matching = tickets[tickets.ticket_id == ref]
    if matching.empty:
        st.error('Historical ticket not found.')
        st.stop()
    matched_ticket = matching.iloc[0].to_dict()
    order_id = str(matched_ticket['order_id'])
else:
    order_id = ref

matching_order = orders[orders.order_id == order_id]
if matching_order.empty:
    st.error('Order not found.')
    st.stop()
order = matching_order.iloc[0].to_dict()
order_tickets = tickets[tickets.order_id == order_id].sort_values('ticket_created_at', ascending=False)
if matched_ticket is None and not order_tickets.empty:
    matched_ticket = order_tickets.iloc[0].to_dict()
history = order_tickets.to_dict('records')
audit = audit_order(order, history)

st.subheader('Order found')
a, b = st.columns(2)
a.metric('Order ID', order_id)
b.metric('Delivery status', str(order.get('delivery_status', '')).replace('_', ' ').title())
st.write('**Courier:**', order.get('courier_partner', 'Unavailable'))
st.write('**Payment:**', order.get('payment_method', 'Unavailable'))
st.write('**Order value:**', '₹{:,.2f}'.format(float(order['order_amount']))
         if pd.notna(order.get('order_amount')) else 'Unavailable')
if matched_ticket:
    st.write('**Latest / matched historical ticket:**', matched_ticket['ticket_id'], '—', matched_ticket['resolution_status'])
if audit['flags']:
    with st.expander(f'Historical policy flags ({len(audit["flags"])})', expanded=True):
        for ticket_id, flag in audit['flags']:
            st.warning(f'{ticket_id} / {flag.rule}: {flag.explanation}')
if audit['requires_reconciliation']:
    st.info('Historical refund/replacement records require agent reconciliation before any new financial action.')

previous_requests = list_requests(DEFAULT_DB, order_id=order_id, limit=100)
with st.expander(f'Locally submitted support requests ({len(previous_requests)})'):
    if previous_requests:
        st.dataframe(pd.DataFrame([{
            'Request ID': r['request_id'], 'Status': r['status'],
            'Action': r['suggested_action'], 'Created (UTC)': r['created_at_utc']
        } for r in previous_requests]), hide_index=True, use_container_width=True)
    else:
        st.caption('No locally submitted requests for this order yet.')

st.subheader('Chat with support')
turns = st.session_state.setdefault('turns', [])
for turn in turns:
    with st.chat_message('user'):
        st.write(turn['user'])
    with st.chat_message('assistant'):
        st.markdown('**' + turn['headline'] + '**')
        st.write(turn['answer'].split('\n\n', 1)[-1])
        if turn.get('ai_explanation'):
            st.caption('Optional local AI wording (not a policy decision): ' + turn['ai_explanation'])
        if turn.get('submitted_request_id'):
            st.caption('Local request: ' + turn['submitted_request_id'])

question = st.chat_input('Ask about delivery, refunds, damage, or follow up…')
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
    # A browser session retained from Phase 2B may not have a submission token yet.
    latest.setdefault('submission_token', uuid.uuid4().hex)
    st.subheader('Instant next step — local database')
    st.write('Suggested action: **' + latest['action'] + '**')
    if latest.get('submitted_request_id'):
        stored = get_request(DEFAULT_DB, latest['submitted_request_id'])
        if stored:
            st.success(f'Request {stored["request_id"]} saved in SQLite. Status: {stored["status"]}.')
            st.download_button('Download request receipt (JSON)',
                               data=json.dumps(stored, indent=2, ensure_ascii=False),
                               file_name=f'{stored["request_id"]}.json', mime='application/json')
    else:
        st.caption('The question and policy guidance will be saved locally in SQLite. '
                   'Do not use sensitive customer information in this unauthenticated demo.')
        if st.button('Submit local support request', type='primary'):
            try:
                new_record = create_request(
                    DEFAULT_DB, token=latest['submission_token'], order_id=order_id,
                    source_ticket_id=matched_ticket['ticket_id'] if matched_ticket else None,
                    customer_question=latest['user'], turn=latest, audit=audit)
                latest['submitted_request_id'] = new_record['request_id']
                st.rerun()
            except StoreError as exc:
                st.error(str(exc))
    if st.button('Clear this conversation'):
        st.session_state['turns'] = []
        st.rerun()

st.caption('Only verified Python SOP rules provide monetary guidance. '
           'SQLite stores demo requests and administrative events; neither Ollama nor the review queue executes payments.')
