# Phase 2A: Refund-SOP validation and regression tests

## Changes
- Distinct keys for Streamlit form vs. submitted lookup (fixes reported exception).
- New pure-Python historical auditing for refund-plus-replacement, cancelled unpaid COD, refund cap, and delayed cash refund violations.
- Order-wide reconciliation gate prevents suggesting a fresh cash refund / replacement when any past ticket already records a refund or replacement, or has unresolved data concerns.
- More informative policy warnings and draft metadata; no external side effects.
- Dataset-backed regression for order ORD-700002.

## Limitations
- Historical CSV refunds are accounting *records*, not proof of bank settlement; flags request reconciliation.
- Aggregating multiple tickets is a conservative control and may surface records for the same transaction more than once.
- The original SOP does not specify every scenario, so unspecified cases require human review.
- Application UI requires manual browser acceptance checks on Ubuntu; automated tests cover policy logic, not a deployed browser session.
- This prototype must not expose real customer data on a public deployment without authentication, authorization, privacy controls and an approved dataset.

## Verify
```bash
python -m pytest -q
python -m compileall -q app.py policy_engine.py policy_audit.py
streamlit run app.py
```
