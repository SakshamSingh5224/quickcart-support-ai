"""Exercise the entire support decision, ticket store, and analytics on fake-only data."""
from uuid import uuid4
import pandas as pd
from auth_store import authenticate, create_user, init_auth
from access_control import (lookup_customer_reference, submit_customer_request,
                            review_request, read_request, authorize_analytics)
from analytics import prepare_data, overview, sqlite_overview
from conversation import authoritative_turn
from policy_audit import audit_order
from scripts.generate_demo_data import generate
from ticket_store import init_db


def test_synthetic_customer_agent_admin_flow(tmp_path):
    generate(tmp_path/'data')
    orders=pd.read_csv(tmp_path/'data/orders_clean.csv')
    tickets=pd.read_csv(tmp_path/'data/support_tickets_clean.csv')
    db=tmp_path/'quickcart.sqlite3'
    init_db(db);init_auth(db)
    create_user(db,username='clientuser',password='Correct-Password-2026',role='customer',customer_id='CUST-DEMO-002')
    create_user(db,username='agentuser',password='Correct-Password-2026',role='agent')
    create_user(db,username='adminuser',password='Correct-Password-2026',role='admin')
    client=authenticate(db,username='clientuser',password='Correct-Password-2026')
    agent=authenticate(db,username='agentuser',password='Correct-Password-2026')
    admin=authenticate(db,username='adminuser',password='Correct-Password-2026')
    order,ticket,history=lookup_customer_reference(client,orders,tickets,'ORD-810002')
    assert ticket['ticket_id']=='TKT-910002'
    audit=audit_order(order,history)
    assert audit['requires_reconciliation'] is True
    turn=authoritative_turn(order,'Item arrived broken, refund please',ticket,history,[])
    assert turn['eligible_refund'] is None and turn['manual_review']
    r=submit_customer_request(client,orders,db,order_id=order['order_id'],
        source_ticket_id=ticket['ticket_id'],token=uuid4().hex,
        customer_question=turn['user'],turn=turn,audit=audit,tickets=tickets)
    assert r['status']=='SUBMITTED'
    assert sqlite_overview(db)['total']==1
    assert review_request(agent,db,request_id=r['request_id'],expected_status='SUBMITTED',
                          new_status='IN_REVIEW',note='Investigate duplicate financial records')['status']=='IN_REVIEW'
    assert read_request(client,orders,db,r['request_id'])['status']=='IN_REVIEW'
    assert authorize_analytics(admin)
    o,t=prepare_data(orders,tickets)
    m=overview(o,t)
    assert m['orders']==36 and m['tickets']==28
    assert m['violating_tickets']>=1
