"""Role isolation, auth throttling and secure account tests for Phase 2E."""
from pathlib import Path
from uuid import uuid4
import pandas as pd
import pytest

from auth_store import (AuthError, active_user, authenticate, create_user,
                        hash_password, init_auth, verify_password)
from access_control import (AccessDenied, agent_queue, authorize_analytics, customer_order,
                            customer_requests, lookup_customer_reference, read_request,
                            request_events, review_request, submit_customer_request)
from ticket_store import init_db, list_events


def db_users(tmp_path):
    db = tmp_path / 'test.sqlite3'
    init_db(db)
    init_auth(db)
    create_user(db, username='alice1', password='Alice!Password_2026',
                role='customer', customer_id='CUST-DEMO-001')
    create_user(db, username='bob_2', password='Bob!!Password_2026',
                role='customer', customer_id='CUST-DEMO-002')
    create_user(db, username='agent1', password='Agent!Password_2026', role='agent')
    create_user(db, username='admin1', password='Admin!Password_2026', role='admin')
    users={}
    for name, password in (('alice1','Alice!Password_2026'), ('bob_2','Bob!!Password_2026'),
                           ('agent1','Agent!Password_2026'),('admin1','Admin!Password_2026')):
        users[name]=authenticate(db, username=name, password=password)
        assert users[name]
    return db, users


def data():
    orders=pd.DataFrame([
        {'order_id':'ORD-810001','customer_id':'CUST-DEMO-001','order_amount':499.0},
        {'order_id':'ORD-810002','customer_id':'CUST-DEMO-002','order_amount':799.0},
    ])
    tickets=pd.DataFrame([
        {'ticket_id':'TKT-910001','order_id':'ORD-810001','customer_id':'CUST-DEMO-001',
         'ticket_created_at':'2026-04-01 00:00:00'},
        {'ticket_id':'TKT-910002','order_id':'ORD-810002','customer_id':'CUST-DEMO-002',
         'ticket_created_at':'2026-04-02 00:00:00'},
    ])
    return orders,tickets


def test_password_hash_salted_verification():
    one=hash_password('long-password-2026!')
    two=hash_password('long-password-2026!')
    assert one != two
    assert 'long-password' not in one
    assert verify_password('long-password-2026!',one)
    assert not verify_password('wrong-password-2026',one)
    assert not verify_password('long-password-2026!', 'broken$hash')
    with pytest.raises(AuthError):
        hash_password('weak')


def test_provisioning_and_credential_storage(tmp_path):
    db, users=db_users(tmp_path)
    alice=active_user(db,users['alice1']['id'])
    assert alice['customer_id']=='CUST-DEMO-001'
    assert 'password_hash' not in alice
    assert authenticate(db,username='ALICE1',password='Alice!Password_2026') == alice
    with pytest.raises(AuthError):
        create_user(db,username='alice1',password='something-long-enough',role='admin')
    with pytest.raises(AuthError):
        create_user(db,username='badagent',password='something-long-enough',role='agent',
                    customer_id='CUST-DEMO-001')
    with pytest.raises(AuthError):
        create_user(db,username='badcustomer',password='something-long-enough',role='customer')


def test_login_lockout_persists_across_attempts(tmp_path):
    db=tmp_path/'app.db';init_db(db);init_auth(db)
    create_user(db,username='customer1',password='correct-password-2026',role='customer',
                customer_id='CUST-DEMO-001')
    for i in range(5):
        assert authenticate(db,username='customer1',password='wrong-password-2026',now=1000+i) is None
    assert authenticate(db,username='customer1',password='correct-password-2026',now=1006) is None
    assert authenticate(db,username='customer1',password='correct-password-2026',now=2000)


def test_customer_cannot_see_another_order_or_ticket(tmp_path):
    db, users=db_users(tmp_path)
    orders,tickets=data()
    one=users['alice1']
    order,ticket,history=lookup_customer_reference(one,orders,tickets,'TKT-910001')
    assert order['order_id']=='ORD-810001' and ticket['ticket_id']=='TKT-910001'
    assert len(history)==1
    with pytest.raises(AccessDenied):
        lookup_customer_reference(one,orders,tickets,'ORD-810002')
    with pytest.raises(AccessDenied):
        lookup_customer_reference(one,orders,tickets,'TKT-910002')
    with pytest.raises(AccessDenied):
        customer_order(one,orders,'ORD-810002')
    with pytest.raises(AccessDenied):
        lookup_customer_reference(one,orders,tickets,'ORD-999999')


def test_customer_submission_ownership_and_status_review(tmp_path):
    db, users=db_users(tmp_path)
    orders,tickets=data()
    payload={'headline':'Policy review required','action':'Request agent review',
             'eligible_refund':None,'voucher':0,'manual_review':True}
    audit={'recorded_refunds_inr':0,'requires_reconciliation':False}
    record=submit_customer_request(users['alice1'],orders,db,
        order_id='ORD-810001',token=uuid4().hex,source_ticket_id='TKT-910001',
        customer_question='Where is my order?',turn=payload,audit=audit,tickets=tickets)
    assert record['status']=='SUBMITTED'
    assert len(customer_requests(users['alice1'],orders,db,order_id='ORD-810001'))==1
    with pytest.raises(AccessDenied):
        customer_requests(users['alice1'],orders,db,order_id='ORD-810002')
    with pytest.raises(AccessDenied):
        submit_customer_request(users['alice1'],orders,db,order_id='ORD-810002',
            token=uuid4().hex,source_ticket_id=None,customer_question='Please help',
            turn=payload,audit=audit)
    with pytest.raises(AccessDenied):
        submit_customer_request(users['alice1'],orders,db,order_id='ORD-810001',
            token=uuid4().hex,source_ticket_id='TKT-910002',customer_question='Please help',
            turn=payload,audit=audit,tickets=tickets)
    with pytest.raises(AccessDenied):
        read_request(users['bob_2'],orders,db,record['request_id'])
    with pytest.raises(AccessDenied):
        request_events(users['bob_2'],orders,db,record['request_id'])
    with pytest.raises(AccessDenied):
        review_request(users['alice1'],db,request_id=record['request_id'],
                       expected_status='SUBMITTED',new_status='IN_REVIEW',note='No.')
    assert len(agent_queue(users['agent1'],db))==1
    with pytest.raises(AccessDenied):
        agent_queue(users['alice1'],db)
    updated=review_request(users['agent1'],db,request_id=record['request_id'],
                           expected_status='SUBMITTED',new_status='IN_REVIEW',
                           note='Investigate courier event before follow-up')
    assert updated['status']=='IN_REVIEW'
    history=list_events(db,record['request_id'])
    assert [x['actor'] for x in history]==['alice1','agent1']
    assert read_request(users['alice1'],orders,db,record['request_id'])['status']=='IN_REVIEW'
    with pytest.raises(AccessDenied):
        authorize_analytics(users['agent1'])
    assert authorize_analytics(users['admin1'])
    assert len(agent_queue(users['admin1'],db))==1
    with pytest.raises(AccessDenied):
        customer_order(users['admin1'],orders,'ORD-810001')


def test_unknown_identity_is_denied(tmp_path):
    db,users=db_users(tmp_path)
    orders,tickets=data()
    with pytest.raises(AccessDenied):
        lookup_customer_reference(None,orders,tickets,'ORD-810001')
    with pytest.raises(AccessDenied):
        authorize_analytics(None)
    with pytest.raises(AccessDenied):
        agent_queue({'role':'customer','username':'x'},db)
