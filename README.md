# QuickCart — Analytics + Policy-Aware Customer Support (Parts 1 and 2)

A local, zero-API-cost Streamlit support prototype for the QuickCart analytics and AI case study. Built on **6,245 cleaned orders and 5,200 cleaned support tickets**, plus the four SOP refund rules. It provides an order/ticket ID lookup, question intent detection, status explanations, SOP-based refund guidance, historical-policy warnings, and a **downloadable draft support request**.

**Important:** This is a **demo**, not a deployed payment or customer-support backend. It does not issue actual refunds/vouchers, update delivery tracking, or create an external ticket. Order IDs are not authentication. Do not deploy actual customer data publicly.

## Run on Ubuntu

```bash
cd ~/Desktop/quickcart-support-ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Visit the URL shown (typically http://localhost:8501). Try `ORD-700002` with “My item came broken, I want a refund”. The example contains a historical replacement + cash refund policy violation; the app warns about it.

Test: `python -m pytest -q`

## What Part 2 does

1. Locates a cleaned order by `ORD-...` or a support ticket by `TKT-...`.
2. Maps plain-language questions to tracking, damaged item, cancellation, or refund intent.
3. Applies Rule 1 (lost/returned full refund; delayed transit ₹100 voucher and 48-hour wait; optional >24h resolution voucher); Rule 2 (replacement **or** full refund); Rule 3 (cancelled-before-ship unpaid COD refund ₹0); Rule 4 (maximum order amount + ₹100).
4. Displays current stored delivery/ticket status and warns when applicable historical refunds conflict with rules.
5. Creates an instant, downloadable JSON **draft** for staff review, without falsely claiming real fulfillment.

Responses use deterministic, auditable policy logic rather than a generative API. No sensitive customer messages are sent to external services.

## Project layout

- `app.py`: Streamlit user interface / CSV lookup
- `policy_engine.py`: rule-based support assistant
- `tests/`: automated SOP tests
- `data/`: cleaned Part 1 source data
- `part1/`: Part 1 report, scripts, charts, cleaning log and policy document

## Limitations and production next steps

- Cleaned data is a historical snapshot, not real-time shipping status.
- Actual refunds/replacements/vouchers require payment and courier APIs, authorization, audit records and idempotency.
- For production, add customer login or OTP + order ownership verification, access control, server-side rate limiting, secure database, and PII handling.
- Damage cases require evidence and an agent's selection of either refund or replacement.
- Refund amounts shown are SOP guidance; don't interpret them as already paid.
- Some historical tickets already violate SOP, so don't use historical outcomes as correct policy examples.

## Part 1

See `part1/README_Part1.md` for cleaning notes and analytic findings. The original Part 1 analysis and chart scripts are preserved **as provided** and contain absolute `/mnt/user-data/...` paths from their original environment; the Part 2 app does not depend on running those scripts.

## GitHub

See the setup steps in the companion chat answer. Never push `.venv/`, secrets, or real private customer information to a public repository. These assignment CSVs should only be committed if you are authorized to publish them.

## Phase 2A — validation and safety hardening (October 2026)

- Fixed Streamlit form/session-state collision by using `lookup_form` for the form and `lookup` for stored query state.
- Added `policy_audit.py` to check historical records against SOP Rules 1–4, including optional damaged-item partial-refund anomalies, missing values, and combined order-level cash refunds.
- Audits **all tickets for the order**, not only the displayed latest ticket; flags possible duplicates/overpayment for **human reconciliation**, not automatic chargebacks.
- When any historical refund or replacement is recorded (or data is incomplete), new refund/replacement guidance is suppressed and a human review draft is offered. Historical records do not prove actual settlement.
- Added unit and dataset regression tests; run `python -m pytest -q`.
- Scope: no actual payment integration, login, support API, or generative AI. The app is still a local-only demo.

### Manual acceptance checks

1. Start Streamlit and submit `ORD-700002` with `My item came broken`; you should see a historical Rule 2 flag and the **Existing support history** decision, not a new ₹799 eligibility offer.
2. Submit `TKT-900002` with `refund`; it should retrieve the same order and warnings.
3. Submit an invalid ID (`ORD-ABC`), then an unknown numeric ID; each should show a clear error/warning.
4. Click the draft action and download the JSON; verify `status` remains `DRAFT_NOT_SUBMITTED` and `requires_historical_reconciliation` is true for the example.
5. Confirm no widget/session-state exception occurs after repeated form submissions.

## Phase 2B — Conversational assistant

The Streamlit app now uses a threaded chat interface with follow-up intent memory. See [PHASE_2B_NOTES.md](PHASE_2B_NOTES.md) for design, testing, and optional free offline Ollama explanations. Monetary recommendations **always** come from the deterministic SOP policy engine, never the LLM. Ollama is not required to run the app.
