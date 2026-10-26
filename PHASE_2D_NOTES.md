# Phase 2D — Admin Analytics Dashboard

**Status:** Implemented; automated Python verification passed in the packaged environment. Interactive Ubuntu Streamlit review still required.

## What was added

- `analytics.py`: pure pandas computations for historical operational measures, rule-based refund exception estimates, historical filters, and aggregate SQLite queries. Can be unit-tested without Streamlit.
- `dashboard_ui.py`: new **Admin analytics** Streamlit workspace with five tabs: Overview, Courier performance, Support SLA & CSAT, Refund policy audit, and Live SQLite requests.
- `app.py`: preserved the existing Customer help / Agent queue flows and added the new workspace in the sidebar.
- `tests/test_analytics.py`: historical fixture tests, missing-data / overlap / date-filter tests, SQLite aggregation tests and dataset reconciliation tests.

## Reproduced Part 1 figures (unfiltered)

| Measure | Value |
|---|---:|
| Unique cleaned orders | 6,245 |
| Unique cleaned historical tickets | 5,200 |
| Total order value (GMV in Part 1 definition) | ₹2,28,63,850 |
| Historical recorded cash refunds | ₹1,00,09,538 |
| Open historical tickets | 582 |
| Average resolution hours, resolved only | 24.47 |
| Valid CSAT ratings | 2,957 |
| Historical SOP exception tickets (unique) | 145 |
| Estimated unique refund-policy leakage | ₹4,67,654 |
| Rule 2 replacement + cash | 40 |
| Rule 3 unpaid COD cancelled refund | 55 |
| Rule 4 exceeding order + ₹100 | 50 |
| Rule 1 delayed full refund | 0 |

## Filter and denominator definitions

1. **Date range:** Inclusive **order placement dates**, not ticket creation dates. Selecting an order cohort includes its matching historical tickets, even if their ticket creation dates lie outside the date range. Date filters do not alter SQLite metrics.
2. **Courier/category:** Filter orders; historical ticket metrics are limited to those matching orders.
3. **Support channel:** Filters historical tickets **only**, so unique order counts and order value remain unchanged.
4. **Lost/delayed percent:** `(# shipped orders marked LOST_IN_TRANSIT or DELAYED_IN_TRANSIT) / (# orders other than CANCELLED_BEFORE_SHIP) × 100`. The original Part 1 summary uses a denominator of **all** orders, so the shipped-only percentage can be different (e.g., Shadowfax 34.03% shipped vs approximately 30.7% all).
5. **Average resolution / SLA:** Resolved tickets with a nonmissing, nonnegative duration. >24h applies to these same tickets.
6. **CSAT:** Scores 1–5 only. Blank and invalid ratings are excluded, not treated as zero.
7. **Total order value:** Sum of valid positive order amounts; invalid amounts still count as distinct orders.
8. **Refund leakage:** The four core anomaly patterns from Part 1, applied to historical recorded amounts. A ticket may trigger multiple rules. The headline unique estimate uses the **largest** applicable per-ticket excess, not the sum of flags. This is an estimated data-policy exception, **not a proven settlement or recoverable cash loss**. More cautious Phase 2A reconciliation flags are not silently reclassified into Part 1 leakage counts.
9. **Live SQLite:** Aggregate *new local* support requests across all records, including those beyond the agent queue's 200-row default. Status counts, active queue, reconciliation, seven-day submissions and audit-event totals are read via SQL. They are NOT added to the 5,200 historical tickets and are not affected by historical cohort filters.

## Manual verification

```bash
cd ~/Desktop/quickcart-support-ai
source .venv/bin/activate
python -m pytest -q
streamlit run app.py --server.address 127.0.0.1
```

In the sidebar choose **Admin analytics**. Confirm the unfiltered numbers, switch to Courier performance, then apply the Shadowfax courier filter. Create a local request in Customer help and check that **Live SQLite requests** increments when you refresh. Return to Agent queue and change its administrative status; the status chart and audit-event total should update upon refresh. Confirm Customer help and Agent queue still work.

## Security and scope

- Local demonstration **only**: neither Admin analytics nor Agent queue has login or role enforcement. Keep bound to `127.0.0.1` and use only approved/synthetic data. Phase 2E will add identity and role-based access controls before any public deployment.
- Dashboard exports include **aggregate courier and rule summary tables only**; no raw customer messages, customer identifiers, or individual support request records are exported from this page.
- SQLite is created in `instance/quickcart.sqlite3` and remains Git-ignored. Do not overwrite or publish this database.
- Charts are based on historical CSV snapshots; there are no live shipping data feeds. Administrative approval is not a monetary authorization and this app does not process any payment.
