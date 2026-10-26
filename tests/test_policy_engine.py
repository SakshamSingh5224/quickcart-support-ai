from policy_engine import classify_question, decide

def order(status, amount=1200, payment='UPI'):
    return {'delivery_status':status,'order_amount':amount,'payment_method':payment}

def test_lost_full_refund():
    d=decide(order('LOST_IN_TRANSIT'),'where is my order')
    assert d.eligible_refund == 1200

def test_returned_full_refund():
    assert decide(order('RETURNED_TO_SELLER'),'refund please').eligible_refund == 1200

def test_delayed_no_full_refund():
    d=decide(order('DELAYED_IN_TRANSIT'),'my parcel is late')
    assert d.eligible_refund == 0 and d.voucher == 100

def test_cancelled_cod_zero():
    d=decide(order('CANCELLED_BEFORE_SHIP',payment='Cash on Delivery (COD)'),'refund')
    assert d.eligible_refund == 0

def test_damage_choice():
    d=decide(order('DELIVERED'),'broken product replacement or refund')
    assert d.eligible_refund == 1200 and d.manual_review

def test_unknown_amount_manual():
    assert decide(order('LOST_IN_TRANSIT',float('nan')),'refund').manual_review

def test_resolved_late_bonus_discretionary():
    d=decide(order('LOST_IN_TRANSIT'),'refund',{'is_open':False,'resolution_hours':26,'refund_amount':0})
    assert d.voucher == 100 and d.eligible_refund == 1200

def test_open_ticket_no_late_bonus():
    d=decide(order('LOST_IN_TRANSIT'),'refund',{'is_open':True,'resolution_hours':40,'refund_amount':0})
    assert d.voucher == 0

def test_intent():
    assert classify_question('My package arrived damaged') == 'damage'
