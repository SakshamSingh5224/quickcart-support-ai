# Synthetic demo data only

The public deployment export is generated independently by `scripts/generate_demo_data.py`.
Its 36 orders and 28 tickets are **entirely fabricated** and use `ORD-81...`, `TKT-91...`,
and `CUST-DEMO-...` IDs. No source CSV, customer message, or original Part 1 attachment
is intentionally included in the public demo export.

Example customer account: link to `CUST-DEMO-002` to access `ORD-810002`.
Other customers cannot view this order. Agent accounts access the support queue, while
admin accounts access the queue and aggregated dashboard.

**No default passwords.** Provision passwords in deployment secrets. The demo stores
password hashes in local SQLite, which can be reset on cloud app restarts. This is not a
production authentication or durable cloud database solution.
