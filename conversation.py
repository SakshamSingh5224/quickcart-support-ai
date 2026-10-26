"""Phase 2B: conversational context and optional localhost-only Ollama explanations."""
import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from policy_engine import classify_question, decide

ALLOWED_INTENTS = {'damage', 'cancel', 'refund', 'tracking', 'general'}
LOCAL_OLLAMA = 'http://127.0.0.1:11434/api/generate'

@dataclass(frozen=True)
class ChatTurn:
    user: str
    intent: str
    headline: str
    answer: str


def resolved_question(message: str, turns: list[dict]) -> tuple[str, str]:
    """Carry forward the previous intent for a short ambiguous follow-up."""
    current = classify_question(message)
    if current != 'general':
        return current, message
    for prev in reversed(turns):
        intent = prev.get('intent', 'general')
        if intent in ALLOWED_INTENTS and intent != 'general':
            if re.search(r'\b(it|this|that|same|what about|how long|why|how|option|instead|then|please|yes|no)\b', message, re.I) or len(message.split()) <= 6:
                seed = {'damage': 'damaged item', 'cancel': 'cancelled order', 'refund': 'refund', 'tracking': 'delivery tracking'}[intent]
                return intent, f'{seed}: {message}'
            break
    return current, message


def authoritative_turn(order: dict, message: str, ticket: dict | None = None,
                       history: list[dict] | None = None, turns: list[dict] | None = None):
    intent, contextual_question = resolved_question(message, turns or [])
    decision = decide(order, contextual_question, ticket, history)
    answer = f'{decision.headline}\n\n{decision.explanation}'
    return {'user': message, 'intent': intent, 'headline': decision.headline,
            'answer': answer, 'action': decision.action,
            'eligible_refund': decision.eligible_refund,
            'voucher': decision.voucher, 'manual_review': decision.manual_review}


def optional_local_explanation(order: dict, turn: dict, model: str = 'qwen2.5:0.5b',
                               endpoint: str = LOCAL_OLLAMA, timeout: int = 25) -> tuple[str | None, str | None]:
    """Use a local model for additional prose ONLY; the policy answer always remains visible.

    The prompt intentionally excludes IDs, customer messages and raw ticket records.
    Never connect to a remote endpoint.
    """
    if endpoint != LOCAL_OLLAMA:
        return None, 'Only the fixed localhost Ollama endpoint is permitted.'
    model = model.strip()
    if not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,70}', model):
        return None, 'Invalid model name.'
    status = str(order.get('delivery_status', '')).upper()
    if status not in {'DELIVERED', 'DELAYED_IN_TRANSIT', 'LOST_IN_TRANSIT', 'RETURNED_TO_SELLER', 'CANCELLED_BEFORE_SHIP'}:
        status = 'OTHER'
    prompt = (
        'You are a customer support writing assistant. Explain the approved statement in plain English, '
        'in at most two sentences. Do not provide any numerical refund amounts, vouchers, guarantees, '
        'delivery ETA, or additional actions. Do not change the policy decision.\n'
        f'Order status category: {status}\n'
        f'Policy result: {turn["headline"]}\n'
        'Write only a friendly general explanation.\n'
    )
    payload = {'model': model, 'prompt': prompt, 'stream': False,
               'options': {'temperature': 0.1, 'num_predict': 90}}
    try:
        request = Request(endpoint, data=json.dumps(payload).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with urlopen(request, timeout=timeout) as response:
            text = str(json.load(response).get('response', '')).strip()
        if not text:
            return None, 'The local model returned no text.'
        # Reject promises, invented quantities, monetary claims; this prose is not used to make decisions.
        if re.search(r'\d|₹|\$|\b(refund issued|guaranteed|approved|will receive|has been sent|automatically)\b', text, re.I):
            return None, 'Model response failed the safety check; showing the verified policy result.'
        return text[:500], None
    except (HTTPError, URLError, TimeoutError, ConnectionError, ValueError, OSError) as exc:
        return None, f'Local Ollama unavailable ({type(exc).__name__}). The policy assistant still works.'
