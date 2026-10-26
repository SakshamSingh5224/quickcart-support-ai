"""QuickCart customer-facing support prototype (local demo, no real payments)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import streamlit as st
from policy_engine import decide
from policy_audit import audit_order

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
st.set_page_config(page_title='QuickCart | Order Help', page_icon='📦', layout='centered')

@st.cache_data
# Cleaned data from Part 1; stay local, no LLM or third-party customer-data transfer.
def load_data():
    orders = pd.read_csv(DATA / 'orders_clean.csv', dtype={'order_id':str,'customer_id':str})
    tickets = pd.read_csv(DATA / 'support_tickets_clean.csv', dtype={'ticket_id':str,'order_id':str,'customer_id':str})
    return orders, tickets

orders, tickets = load_data()
st.title('📦 QuickCart Order Help')
st.caption('Policy-aware support prototype · Local CSV lookup · No paid APIs')
st.info('Demo only: IDs alone are not authentication. Do not deploy with real customer data without identity verification, authorization, and secure storage. Actions below create downloadable **draft requests**, not live refunds, vouchers, or courier updates.')

with st.form('lookup_form'):
    reference = st.text_input('Enter order ID or support ticket ID', placeholder='ORD-700002 or TKT-900002')
    question = st.text_area('How can we help?', placeholder='My item arrived broken. Can I get a refund?', height=85)
    sent = st.form_submit_button('Check order and policy', type='primary', use_container_width=True)

if sent:
    ref = reference.strip().upper()
    if not re.fullmatch(r'(ORD-\d+|TKT-\d+)', ref):
        st.error('Use a valid ID such as ORD-700002 or TKT-900002.')
        st.stop()
    if not question.strip():
        st.error('Please type a question.')
        st.stop()
    st.session_state.pop('draft', None)
    st.session_state['lookup'] = (ref, question.strip())

if 'lookup' not in st.session_state:
    st.markdown('**Try:** `ORD-700002` + “My item came broken and I want a refund”.')
    st.stop()

ref, question = st.session_state['lookup']
matched_ticket = None
if ref.startswith('TKT-'):
    matching = tickets[tickets.ticket_id == ref]
    if matching.empty:
        st.warning('Ticket not found in the provided dataset.')
        st.stop()
    matched_ticket = matching.iloc[0].to_dict()
    order_id = str(matched_ticket['order_id'])
else:
    order_id = ref

matching_order = orders[orders.order_id == order_id]
if matching_order.empty:
    st.warning('Order not found in the provided dataset.')
    st.stop()
order = matching_order.iloc[0].to_dict()
order_tickets = tickets[tickets.order_id == order_id].sort_values('ticket_created_at', ascending=False)
if matched_ticket is None and not order_tickets.empty:
    matched_ticket = order_tickets.iloc[0].to_dict()

st.subheader('Order found')
a, b = st.columns(2)
a.metric('Order ID', order_id)
b.metric('Delivery status', str(order['delivery_status']).replace('_',' ').title())
st.write('**Courier:**', order['courier_partner'])
st.write('**Payment:**', order['payment_method'])
st.write('**Order value:**', ('₹{:,.2f}'.format(float(order['order_amount'])) if pd.notna(order['order_amount']) else 'Unavailable'))
if matched_ticket:
    st.write('**Latest / matched ticket:**', matched_ticket['ticket_id'], '—', matched_ticket['resolution_status'])
    st.caption('Historical recorded cash refund: ₹{:,.2f}. This is dataset history, not a payment issued by this app.'.format(float(matched_ticket.get('refund_amount', 0) or 0)))

history = order_tickets.to_dict('records')
audit = audit_order(order, history)
response = decide(order, question, matched_ticket, history)
st.subheader('Support assistant')
st.success('**' + response.headline + '**')
st.write(response.explanation)
st.caption('Refund and voucher figures indicate SOP eligibility, not confirmed payment. Late vouchers are discretionary. Refunds must never exceed order value + ₹100 (Rule 4).')

if audit['flags']:
    st.warning('Historical policy / data review flags (these are recorded data, not new payments):')
    for ticket_id, flag in audit['flags']:
        st.write(f'- **{ticket_id} / {flag.rule}:** {flag.explanation}')
if audit['requires_reconciliation']:
    st.info('New financial actions are blocked in this demo until an authorized agent reconciles the historical record.')

st.subheader('Instant next step')
st.write('Generate a structured request for the support team:')
if st.button(response.action, type='primary'):
    request = {
        'request_id': 'DEMO-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f'),
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'order_id': order_id,
        'ticket_id': matched_ticket['ticket_id'] if matched_ticket else None,
        'customer_question': question,
        'action_requested': response.action,
        'policy_recommended_cash_refund_inr': response.eligible_refund,
        'policy_recommended_voucher_inr': response.voucher,
        'requires_human_review': response.manual_review or audit['requires_reconciliation'],
        'historical_recorded_refunds_inr': audit['recorded_refunds_inr'],
        'requires_historical_reconciliation': audit['requires_reconciliation'],
        'status': 'DRAFT_NOT_SUBMITTED',
        'notice': 'Prototype draft only. No refund, replacement, voucher or ticket was created in an external system.'
    }
    st.session_state['draft'] = request
if 'draft' in st.session_state and (st.session_state['draft']['order_id'] == order_id):
    st.download_button('Download support request (JSON)',
                       data=json.dumps(st.session_state['draft'], indent=2, ensure_ascii=False),
                       file_name='quickcart_support_request.json', mime='application/json', use_container_width=True)
    st.caption('Share this draft with an authorized support agent for verification and fulfillment.')

with st.expander('About the decision logic'):
    st.write('The assistant uses keyword-based intent recognition plus deterministic rules from `sop_policy_rules.docx`. It does not invent shipment scans, courier ETAs, or transaction confirmations.')
