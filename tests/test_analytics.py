import pytest
"""Phase 2D: analytics metrics, denominator rules, missing data and SQLite live counts."""
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from analytics import (
    attach_order_facts, courier_performance, delivery_breakdown, historical_leakage,
    overview, prepare_data, select_cohort, sqlite_overview, support_by_channel,
    weekly_ticket_activity,
)
from ticket_store import connection, create_request, init_db, update_request_status


def fixtures():
    orders = pd.DataFrame([
        {'order_id':'ORD-1', 'order_date':'2026-01-01 12:00', 'courier_partner':'A',
         'product_category':'Electronics', 'delivery_status':'DELIVERED', 'order_amount':100,
         'payment_method':'UPI'},
        {'order_id':'ORD-2', 'order_date':'2026-01-02 09:00', 'courier_partner':'A',
         'product_category':'Fashion', 'delivery_status':'DELAYED_IN_TRANSIT', 'order_amount':200,
         'payment_method':'UPI'},
        {'order_id':'ORD-3', 'order_date':'2026-01-03 12:00', 'courier_partner':'B',
         'product_category':'Fashion', 'delivery_status':'CANCELLED_BEFORE_SHIP', 'order_amount':300,
         'payment_method':'Cash on Delivery (COD)'},
    ])
    tickets = pd.DataFrame([
        {'ticket_id':'TKT-1','order_id':'ORD-1','ticket_created_at':'2026-01-02 13:00',
         'resolution_status':'Resolved - Replacement Sent','refund_amount':100,'resolution_hours':10,
         'csat_score':5,'channel':'In-App Chat','is_open':False},
        {'ticket_id':'TKT-2','order_id':'ORD-2','ticket_created_at':'2026-01-05 13:00',
         'resolution_status':'Resolved - Full Refund Issued','refund_amount':200,'resolution_hours':30,
         'csat_score':99,'channel':'Email','is_open':'False'},
        {'ticket_id':'TKT-3','order_id':'ORD-3','ticket_created_at':'2026-01-05 14:00',
         'resolution_status':'Open - Awaiting Courier Update','refund_amount':50,'resolution_hours':None,
         'csat_score':None,'channel':'Email','is_open':'True'},
    ])
    return prepare_data(orders, tickets)


def test_summary_denominators_and_data_types():
    o,t=fixtures(); m=overview(o,t)
    assert m['orders']==3 and m['shipped_orders']==2
    assert m['lost_delayed_rate_pct']==50.0  # 1 out of 2 SHIPPED, not 1 out of 3
    assert m['tickets']==3 and m['open_tickets']==1
    assert m['avg_resolution_hours']==20.0
    assert m['resolved_over_24h_pct']==50.0
    assert m['rated_tickets']==1 and m['avg_csat']==5
    assert m['recorded_refunds_inr']==350


def test_part1_violation_patterns_and_unique_excess():
    o,t=fixtures()
    flagged, by_rule=historical_leakage(attach_order_facts(o,t))
    assert flagged['any_violation'].sum()==3
    assert flagged['estimated_leak_inr'].sum()==250  # R2 100, R1 100, R3 50
    assert dict(zip(by_rule.rule,by_rule.flagged_tickets))=={
        'R1_delayed_full_refund':1,'R2_replacement_plus_cash':1,
        'R3_COD_cancelled_refund':1,'R4_exceeds_cap':0}
    assert by_rule['per_rule_estimate_inr'].sum()==250


def test_overlapping_flags_do_not_double_count_unique_leak():
    o,t=fixtures()
    o.loc[o.order_id=='ORD-3','order_amount']=1
    t.loc[t.ticket_id=='TKT-3','refund_amount']=500
    flagged, by_rule=historical_leakage(attach_order_facts(o,t))
    third=flagged[flagged.ticket_id=='TKT-3'].iloc[0]
    assert third['R3_COD_cancelled_refund'] and third['R4_exceeds_cap']
    assert third['estimated_leak_inr']==500  # max(500, 399)
    assert by_rule['per_rule_estimate_inr'].sum()>flagged['estimated_leak_inr'].sum()


def test_missing_price_does_not_produce_fictitious_cap_violation():
    o,t=fixtures()
    o.loc[o.order_id=='ORD-1','order_amount']=None
    flagged,_=historical_leakage(attach_order_facts(o,t))
    first=flagged[flagged.ticket_id=='TKT-1'].iloc[0]
    assert not first['R4_exceeds_cap'] and first['missing_amount_for_cap']
    assert overview(o,t)['invalid_order_amounts']==1
    assert overview(o,t)['uncertain_cap_tickets']==1


def test_date_range_is_inclusive_and_is_order_date_not_ticket_date():
    o,t=fixtures()
    selected_o,selected_t=select_cohort(o,t,start_date=date(2026,1,1),end_date=date(2026,1,1))
    assert selected_o.order_id.tolist()==['ORD-1']
    assert selected_t.ticket_id.tolist()==['TKT-1']  # created Jan 2, still included


def test_filter_courier_and_category():
    o,t=fixtures()
    so,st=select_cohort(o,t,couriers=['A'],categories=['Fashion'])
    assert so.order_id.tolist()==['ORD-2'] and st.ticket_id.tolist()==['TKT-2']


def test_channel_affects_only_ticket_metrics():
    o,t=fixtures()
    so,st=select_cohort(o,t,channels=['Email'])
    assert len(so)==3 and len(st)==2
    assert overview(so,st)['orders']==3


def test_empty_selections_never_reuse_all():
    o,t=fixtures()
    so,st=select_cohort(o,t,couriers=[])
    assert len(so)==len(st)==0
    m=overview(so,st)
    assert m['lost_delayed_rate_pct'] is None
    assert m['avg_resolution_hours'] is None
    assert m['avg_csat'] is None
    assert len(courier_performance(so,st))==0
    assert len(support_by_channel(st))==0


def test_resolved_negative_duration_excluded():
    o,t=fixtures()
    t.loc[t.ticket_id=='TKT-1','resolution_hours']=-3
    m=overview(o,t)
    assert m['avg_resolution_hours']==30
    assert m['resolved_tickets']==1


def test_duplicate_order_id_fails():
    o,t=fixtures()
    with pytest.raises(ValueError,match='one non-null'):
        prepare_data(pd.concat([o,o.iloc[[0]]]),t)


def test_duplicate_ticket_id_fails():
    o,t=fixtures()
    with pytest.raises(ValueError,match='one non-null'):
        prepare_data(o,pd.concat([t,t.iloc[[0]]]))


def test_missing_required_column_fails():
    o,t=fixtures()
    with pytest.raises(ValueError,match='missing required columns'):
        prepare_data(o.drop(columns=['order_amount']),t)


def test_original_frames_not_changed():
    o,t=fixtures()
    o_before=o.copy(deep=True);t_before=t.copy(deep=True)
    select_cohort(o,t,start_date=date(2026,1,1),end_date=date(2026,1,2))
    pd.testing.assert_frame_equal(o,o_before)
    pd.testing.assert_frame_equal(t,t_before)


def test_courier_breakdown_with_cancelled_excluded():
    o,t=fixtures()
    table=courier_performance(o,t)
    b=table[table.courier_partner=='B'].iloc[0]
    assert b['shipped_orders']==0 and pd.isna(b['lost_delayed_rate_pct'])
    a=table[table.courier_partner=='A'].iloc[0]
    assert a['lost_delayed_rate_pct']==50


def test_weekly_ticket_counts_partition_set():
    o,t=fixtures()
    weeks=weekly_ticket_activity(t)
    assert weeks.tickets_created.sum()==3
    assert weeks.currently_open.sum()==1


def test_empty_timeseries():
    o,t=fixtures()
    assert weekly_ticket_activity(t.iloc[0:0]).empty
    assert delivery_breakdown(o.iloc[0:0]).empty


def test_sqlite_dashboard_is_zero_with_no_local_tickets(tmp_path):
    db=tmp_path/'demo.sqlite3';init_db(db)
    live=sqlite_overview(db)
    assert live['total']==live['active']==live['needs_reconciliation']==0
    assert live['audit_events']==0 and live['daily'].empty
    assert len(live['by_status'])==5 and live['by_status']['requests'].sum()==0


def _request(db, order_id='ORD-123', reconciliation=False):
    return create_request(db,token=uuid4().hex,order_id=order_id,
                          customer_question='Please assist',
                          turn={'headline':'Review','action':'Contact agent',
                                'eligible_refund':None,'voucher':0,'manual_review':True},
                          audit={'recorded_refunds_inr':100 if reconciliation else 0,
                                 'requires_reconciliation':reconciliation})


def test_sqlite_dashboard_updates_after_status_transition(tmp_path):
    db=tmp_path/'demo.sqlite3';init_db(db)
    req=_request(db,reconciliation=True)
    first=sqlite_overview(db)
    assert first['total']==1 and first['active']==1
    assert first['needs_reconciliation']==1
    assert first['audit_events']==1
    assert first['by_status'].set_index('status').loc['SUBMITTED','requests']==1
    assert first['submitted_last_7_days']==1
    update_request_status(db,request_id=req['request_id'],expected_status='SUBMITTED',
                          new_status='IN_REVIEW',reviewer='test-reviewer',note='Manual review started')
    after=sqlite_overview(db)
    assert after['by_status'].set_index('status').loc['IN_REVIEW','requests']==1
    assert after['audit_events']==2


def test_sqlite_active_excludes_terminal_states(tmp_path):
    db=tmp_path/'demo.sqlite3';init_db(db)
    one=_request(db)
    update_request_status(db,request_id=one['request_id'],expected_status='SUBMITTED',
                          new_status='REJECTED',reviewer='test',note='No action required')
    assert sqlite_overview(db)['active']==0


def test_sqlite_counts_all_not_just_first_200(tmp_path):
    db=tmp_path/'demo.sqlite3';init_db(db)
    # Set up the equivalent of a large queue using SQL, checking dashboard reads
    # all rows rather than the default 200-row UI queue limit.
    example=_request(db)
    with connection(db) as con:
        template=con.execute('SELECT * FROM support_requests WHERE request_id=?',(example['request_id'],)).fetchone()
        columns=[name for name in template.keys() if name not in ('request_id','submission_token')]
        ins='INSERT INTO support_requests (request_id,submission_token,'+','.join(columns)+') VALUES (' + ','.join(['?']*(len(columns)+2))+')'
        values=[template[col] for col in columns]
        con.executemany(ins, [('QC-TEST%016d'%i, uuid4().hex,*values) for i in range(225)])
    assert sqlite_overview(db)['total']==226
    assert sqlite_overview(db)['active']==226


@pytest.mark.original_dataset
def test_dataset_phase1_reconciliation():
    """Reproduce original Part 1 count and refund-leak findings on supplied snapshot."""
    root = Path(__file__).resolve().parents[1] / 'data'
    o, t = prepare_data(pd.read_csv(root / 'orders_clean.csv'),
                        pd.read_csv(root / 'support_tickets_clean.csv'))
    m = overview(o, t)
    assert m['orders'] == 6245
    assert m['tickets'] == 5200
    assert m['gmv_inr'] == 22863850
    assert m['recorded_refunds_inr'] == 10009538
    assert m['open_tickets'] == 582
    assert m['rated_tickets'] == 2957
    assert m['violating_tickets'] == 145
    assert m['estimated_leak_inr'] == 467654
    flagged, rules = historical_leakage(attach_order_facts(o, t))
    counts = dict(zip(rules['rule'], rules['flagged_tickets']))
    assert counts == {
        'R1_delayed_full_refund': 0, 'R2_replacement_plus_cash': 40,
        'R3_COD_cancelled_refund': 55, 'R4_exceeds_cap': 50}
    assert round(float(rules['per_rule_estimate_inr'].sum()), 2) == 467654
    assert len(flagged) == 5200


def test_historical_dashboard_snapshot_is_separate_from_live_sqlite(tmp_path):
    """New customer support requests must never increase historical ticket counts."""
    o,t=fixtures()
    original = overview(o,t)
    db=tmp_path/'new.sqlite3';init_db(db)
    _request(db)
    _request(db)
    assert sqlite_overview(db)['total']==2
    assert overview(o,t)==original
