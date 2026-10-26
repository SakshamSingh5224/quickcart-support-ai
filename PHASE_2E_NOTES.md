# QuickCart Phase 2E — Authentication, Authorization, CI and Safe Demo

## Scope

This release upgrades **Phase 2D** without changing the original four refund SOP rules,
Phase 2B conversation engine, Phase 2C ticket workflow, or Phase 2D analytical calculations.

### New modules

- `auth_store.py`: salted PBKDF2-HMAC-SHA256 password hashes, first-run user provisioning,
  active user profiles, and SQLite-backed 5-attempt/15-minute login throttling.
- `access_control.py`: role checks, CSV `customer_id` ownership on order and historical-ticket
  lookups, per-order request visibility, authenticated agent updates, and admin-only analytics.
- `app.py`: login/logout, 1-hour browser session timeout, workspace selection by role,
  signed-in audit actor, customer-owned order access and locally stored request receipts.
- `scripts/manage_users.py`: interactive local account creation (password never passed on CLI).
- `scripts/generate_demo_data.py`: synthetic demonstration data with sample order `ORD-810002`.
- `scripts/build_public_demo.py`: allowlisted public export with *no original data or Part 1 assets*.
- `scripts/check_demo_safety.py`: rejects files outside the synthetic data conventions.
- `.github/workflows/ci.yml`: tests, byte compilation, synthetic release safety check.

### Roles

| Role | Customer lookup | Own support requests | Agent queue | Admin analytics |
| --- | --- | --- | --- | --- |
| Customer | Only their `customer_id` | Yes | No | No |
| Agent | No | No | Yes | No |
| Admin | No | No | Yes | Yes |

Accounts are provisioned by a developer/admin, not self-registered. The customer account's
`customer_id` must match a value in `data/orders_clean.csv`. An order/ticket ID on its own
is never sufficient for access.

### Upgrade an existing Ubuntu Desktop project

1. Back up the whole existing `quickcart-support-ai/` directory; this also protects
   `instance/quickcart.sqlite3` and your Git metadata.
2. Unzip `quickcart-phase2e-update.zip` over `~/Desktop`. **This update has no data/ or
   part1/ folder**, so those existing local directories remain unchanged.
3. `cd ~/Desktop/quickcart-support-ai`
4. `source .venv/bin/activate` (create it with `python3 -m venv .venv` if absent)
5. `pip install -r requirements.txt`
6. `python -m pytest -q` — runs all tests including the original snapshot regression tests
   if you have your real local cleaned CSVs.
7. Provision separate local accounts (enter strong passwords interactively):

```bash
python -m scripts.manage_users create --username quickadmin --role admin
python -m scripts.manage_users create --username supportagent --role agent
# The original ORD-700002 belongs to customer_id CUST-12232.
python -m scripts.manage_users create --username samplecustomer --role customer --customer-id CUST-12232
streamlit run app.py --server.address 127.0.0.1
```

Existing Phase 2C requests remain in the SQLite database. App-user tables are added on first run.
Customer and agent data remain separated. If you previously uploaded the source datasets to
GitHub, keep that repository **private** until the dataset owner's sharing permission is clear.

### Try it

1. Log in with `samplecustomer`. Lookup `ORD-700002`, ask about a broken item, and submit a
   support request. Historical replacement + recorded refund triggers review, not another refund.
2. Log out and sign in as `supportagent`. Open the agent queue, advance the request to IN_REVIEW,
   and add a reason. The audit actor equals the signed-in username, not an arbitrary label.
3. Log in as `quickadmin`: you can see the queue and the Phase 2D analytics dashboard.
4. Log in with a **different customer account** and verify `ORD-700002` and `TKT-900002`
   are inaccessible. Wrong order/ticket IDs show the same generic message.
5. Test that 5 incorrect logins lock the username for 15 minutes; the app also expires a
   session after 1 hour. Never put real customer passwords into demo recordings.

### Build a separate publishable demo

Generate the public demo in a **different directory / repository**:

```bash
cd ~/Desktop/quickcart-support-ai
python -m scripts.build_public_demo --output ~/Desktop/quickcart-public-demo
python -m scripts.check_demo_safety ~/Desktop/quickcart-public-demo
```

The generated demo contains 36 entirely fabricated orders and 28 tickets. Example data:
`ORD-810002` and `TKT-910002` belong to `CUST-DEMO-002`.

You can run it locally and create its accounts with the same provisioning command. For public
Streamlit Community Cloud, configure **root-level app secrets** (not in a committed file):

```toml
QC_PUBLIC_DEMO = "1"
QC_BOOTSTRAP_ADMIN_USER = "quickadmin"
QC_BOOTSTRAP_ADMIN_PASSWORD = "<generate-a-unique-strong-password>"
QC_BOOTSTRAP_AGENT_USER = "supportagent"
QC_BOOTSTRAP_AGENT_PASSWORD = "<generate-a-different-strong-password>"
QC_BOOTSTRAP_CUSTOMER_USER = "samplecustomer"
QC_BOOTSTRAP_CUSTOMER_PASSWORD = "<generate-a-third-strong-password>"
QC_BOOTSTRAP_CUSTOMER_ID = "CUST-DEMO-002"
```

Create a new GitHub repo `quickcart-public-demo` (not the repo with the original CSVs),
commit **only** its synthetic export, and deploy entry point `app.py` from this new repo
at https://share.streamlit.io . Set secrets in the Cloud app's advanced configuration,
**not** in `.streamlit/secrets.toml` tracked by Git.

Community Cloud's filesystem is not a durable store: users, support requests, and audit events
in local SQLite **may be lost on restart/redeployment**. This makes the public version a
*stateless-ish demonstration*, not a reliable multi-user application. Password-based login
in this sample is also not equivalent to a hardened OIDC provider. For real production,
use OAuth/OIDC, centralized revocable sessions, MFA, server-side authorization on every
API, persistent managed database, encryption, monitoring and data-retention controls.

The optional local Ollama generator is disabled in public-demo mode; policy-based answers
remain available without a model or paid API.

### CI

- `pytest -q` runs all tests if the original dataset exists locally.
- `pytest -q -m "not original_dataset"` runs tests that do not require private customer CSVs.
- GitHub Actions runs the second suite, byte-compiles code, and checks the synthetic export.
- No GitHub Actions job connects to or executes real refunds, customer notification, or payments.

### Security and limitations

- Account provisioning is an explicit trusted administrative action. No default passwords.
- Password hashes use random 16-byte salts and 600,000 PBKDF2-SHA256 iterations.
- Customer ownership is checked against `orders.customer_id` and `tickets.customer_id`.
- The customer interface never exposes another user's ticket or SQLite support request.
- Admin analytics use historical aggregates. Agents may inspect the demo's full review queue.
- Refund eligibility remains policy-controlled and requires human authorization for any
  external action. The FOLLOW_UP_APPROVED status is **not** monetary approval.
- Unauthenticated sign-in and all role checks are for educational demonstration. No claim
  of independent security testing, production assurance, or durable public cloud persistence.
