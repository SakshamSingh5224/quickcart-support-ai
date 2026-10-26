from conversation import authoritative_turn, resolved_question, optional_local_explanation

ORDER = {'order_amount': 799, 'delivery_status': 'DELIVERED', 'payment_method': 'UPI'}

def test_followup_carries_damage_intent():
    intent, query = resolved_question('What about that option?', [{'intent': 'damage'}])
    assert intent == 'damage' and 'damaged item' in query

def test_new_intent_overrides_history():
    intent, _ = resolved_question('Where is my order?', [{'intent': 'damage'}])
    assert intent == 'tracking'

def test_no_history_general():
    assert resolved_question('Hello!', [])[0] == 'general'

def test_damage_turn_is_policy_controlled():
    t = authoritative_turn(ORDER, 'My item is broken')
    assert t['manual_review'] and t['eligible_refund'] == 799

def test_followup_keeps_policy():
    t = authoritative_turn(ORDER, 'What about that option?', turns=[{'intent': 'damage'}])
    assert t['manual_review'] and 'Replacement or full refund' in t['headline']

def test_historical_record_blocks_financial_advice():
    t = authoritative_turn(ORDER, 'Refund please', history=[{'ticket_id':'TKT-1','refund_amount':799,'resolution_status':'Resolved - Replacement Sent'}])
    assert t['manual_review'] and t['eligible_refund'] is None

def test_llm_remote_endpoint_rejected():
    answer, error = optional_local_explanation(ORDER, {'headline':'Review'}, endpoint='https://example.com/api')
    assert answer is None and 'localhost' in error

def test_llm_invalid_model_rejected():
    answer, error = optional_local_explanation(ORDER, {'headline':'Review'}, model='bad model!')
    assert answer is None and error

def test_llm_offline_gracefully(monkeypatch):
    import conversation
    def offline(*args, **kwargs):
        raise ConnectionError('offline')
    monkeypatch.setattr(conversation, 'urlopen', offline)
    answer, error = optional_local_explanation(ORDER, {'headline':'Support review required'})
    assert answer is None and 'still works' in error

def test_history_switch_intent():
    intent, _ = resolved_question('Cancel my order', [{'intent': 'damage'}])
    assert intent == 'cancel'
