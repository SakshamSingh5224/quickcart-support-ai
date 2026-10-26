"""QuickCart customer help: chat UI, deterministic SOP, optional localhost LLM."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
from conversation import authoritative_turn, optional_local_explanation
from policy_audit import audit_order

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
st.set_page_config(page_title='QuickCart | Order Help', page_icon='📦', layout='centered')

@st.cache_data
def load_data():
    return (pd.read_csv(DATA / 'orders_clean.csv', dtype={'order_id': str, 'customer_id': str}),
            pd.read_csv(DATA / 'support_tickets_clean.csv', dtype={'ticket_id': str, 'order_id': str, 'customer_id': str}))

orders, tickets = load_data()
st.title('📦 QuickCart Order Help')
st.caption('Phase 2B · Conversation memory · Local policy decisions · Optional local AI')
st.warning('Demo only: order/ticket IDs are not authentication. Do not expose real customer data publicly. No refunds, replacements, vouchers or live tickets are issued here.')

with st.sidebar:
    st.header('Assistant settings')
    use_llm = st.toggle('Optional local Ollama explanations', value=False,
                        help='Requires Ollama installed locally; never sends raw CSVs, customer messages or IDs to the model.')
    model = st.text_input('Installed Ollama model', value='qwen2.5:0.5b', disabled=not use_llm)
    st.caption('The Python policy answer is authoritative; AI text is supplemental only.')

with st.form('order_lookup_form'):
    reference = st.text_input('Order ID or ticket ID', placeholder='ORD-700002')
    submitted = st.form_submit_button('Load order', type='primary')

if submitted:
    ref = reference.strip().upper()
    if not re.fullmatch(r'(ORD-\d+|TKT-\d+)', ref):
        st.error('Use a valid ID such as ORD-700002 or TKT-900002.')
    else:
        # Do not modify a widget key; use separate app state.
        if ref != st.session_state.get('active_ref'):
            st.session_state['turns'] = []
            st.session_state.pop('draft', None)
        st.session_state['active_ref'] = ref

ref = st.session_state.get('active_ref')
if not ref:
    st.info('Load an order, then chat about delivery, cancellations, damaged items or refunds.')
    st.stop()

matched_ticket = None
if ref.startswith('TKT-'):
    matching = tickets[tickets.ticket_id == ref]
    if matching.empty:
        st.error('Ticket not found.')
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
st.write('**Order value:**', '₹{:,.2f}'.format(float(order['order_amount'])) if pd.notna(order.get('order_amount')) else 'Unavailable')
if matched_ticket:
    st.write('**Latest / matched ticket:**', matched_ticket['ticket_id'], '—', matched_ticket['resolution_status'])
if audit['flags']:
    with st.expander(f'Historical policy flags ({len(audit["flags"])})', expanded=True):
        for ticket_id, flag in audit['flags']:
            st.warning(f'{ticket_id} / {flag.rule}: {flag.explanation}')
if audit['requires_reconciliation']:
    st.info('Historical refund/replacement records require agent reconciliation before any new financial action.')

st.subheader('Chat with support')
turns = st.session_state.setdefault('turns', [])
for turn in turns:
    with st.chat_message('user'):
        st.write(turn['user'])
    with st.chat_message('assistant'):
        st.markdown('**' + turn['headline'] + '**')
        st.write(turn['answer'].split('\n\n', 1)[-1])
        if turn.get('ai_explanation'):
            st.caption('Optional local AI wording (not the policy decision): ' + turn['ai_explanation'])

question = st.chat_input('Ask about delivery, refund, damage, or follow up…')
if question:
    if len(question) > 1200:
        st.error('Keep messages to 1,200 characters or fewer.')
    else:
        turn = authoritative_turn(order, question, matched_ticket, history, turns)
        if use_llm:
            extra, error = optional_local_explanation(order, turn, model)
            if extra:
                turn['ai_explanation'] = extra
            elif error:
                st.caption(error)
        turns.append(turn)
        st.session_state.pop('draft', None)
        st.rerun()

if turns:
    latest = turns[-1]
    st.subheader('Instant next step')
    st.write('Recommended draft action: **' + latest['action'] + '**')
    if st.button('Prepare support request', type='primary'):
        draft = {
            'request_id': 'DEMO-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f'),
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'order_id': order_id,
            'ticket_id': matched_ticket['ticket_id'] if matched_ticket else None,
            'customer_question': latest['user'],
            'policy_headline': latest['headline'],
            'action_requested': latest['action'],
            'policy_recommended_cash_refund_inr': latest['eligible_refund'],
            'policy_recommended_voucher_inr': latest['voucher'],
            'requires_human_review': latest['manual_review'] or audit['requires_reconciliation'],
            'requires_historical_reconciliation': audit['requires_reconciliation'],
            'historical_recorded_refunds_inr': audit['recorded_refunds_inr'],
            'status': 'DRAFT_NOT_SUBMITTED',
            'notice': 'No financial or ticket action was executed.'
        }
        st.session_state['draft'] = draft
    if 'draft' in st.session_state and st.session_state['draft']['order_id'] == order_id:
        st.download_button('Download support request (JSON)',
                           data=json.dumps(st.session_state['draft'], indent=2, ensure_ascii=False),
                           file_name='quickcart_support_request.json', mime='application/json')
    if st.button('Clear this conversation'):
        st.session_state['turns'] = []
        st.session_state.pop('draft', None)
        st.rerun()

st.caption('The four written QuickCart SOP rules and historical audit determine all financial guidance. AI cannot override them.')
