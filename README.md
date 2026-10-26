# QuickCart — Order Support AI & Operations Analytics

**Phase 2E complete locally:** data cleaning and analytics (Part 1), deterministic support
policy (2A), conversational chat with optional *localhost* Ollama (2B), SQLite ticket
management (2C), Streamlit admin analytics (2D), and demo login/RBAC, CI and synthetic
public deployment kit (2E).

> **Portfolio/demo software, not a real commerce service.** No refunds, vouchers,
> replacements, or courier updates are executed. Historical CSVs and ticket messages may
> contain customer data; do **not** publish or deploy the original datasets without permission.

## Project architecture

```text
Streamlit UI (app.py)
  ├─ Local account login (auth_store.py)
  ├─ Role and customer ownership checks (access_control.py)
  ├─ Customer chat → conversation.py → policy_engine.py + policy_audit.py
  ├─ Authenticated agent queue → ticket_store.py → instance/quickcart.sqlite3
  └─ Admin operations dashboard → dashboard_ui.py → analytics.py
Data: data/orders_clean.csv + data/support_tickets_clean.csv (local/private)
Tests: tests/; GitHub Actions: .github/workflows/ci.yml
Synthetic release: scripts/build_public_demo.py
```

## Local setup on Ubuntu

```bash
cd ~/Desktop/quickcart-support-ai
python3 -m venv .venv          # omit if you already have the environment
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
```

The account system uses a local SQLite file. Create logins with passwords prompted
interactively (passwords are not stored in source files):

```bash
python -m scripts.manage_users create --username quickadmin --role admin
python -m scripts.manage_users create --username supportagent --role agent
python -m scripts.manage_users create --username samplecustomer --role customer --customer-id CUST-12232
streamlit run app.py --server.address 127.0.0.1
```

`CUST-12232` is the owner of the original sample order `ORD-700002` (only in the private
historical dataset). Customer identities cannot look up another customer's orders/tickets.
Agent identities can update administrative ticket statuses; only admins see operations
analytics. All actors are recorded against their login. No account self-registration.

## Release a separate safe public demo

Never deploy the local project directory with the original case-study datasets. Generate
an allowlisted copy containing synthetic data instead:

```bash
python -m scripts.build_public_demo --output ~/Desktop/quickcart-public-demo
python -m scripts.check_demo_safety ~/Desktop/quickcart-public-demo
```

The public package has its own fabricated sample `ORD-810002`, belonging to
`CUST-DEMO-002`; it **never** includes original Part 1 reports, CSVs or messages.
Push that folder to a **separate** GitHub repository and deploy `app.py` via Streamlit
Community Cloud. Bootstrap three unique strong-password demo logins through **Streamlit
app secrets**, described in [PHASE_2E_NOTES.md](PHASE_2E_NOTES.md). The cloud database
is ephemeral; ticket history and accounts may reset when the app restarts.

## Verification

```bash
python -m pytest -q                          # full suite against original local data
python -m pytest -q -m "not original_dataset" # source-only CI suite
```

For the original Part 1 findings and charts, see the retained local `part1/` folder and
`PHASE_2D_NOTES.md`. Full Phase 2E instructions and security limitations are in
[PHASE_2E_NOTES.md](PHASE_2E_NOTES.md).

**Limits:** Local password authentication is an educational example, not a substitute
for managed OIDC, MFA, durable encrypted persistence, revocable sessions, or formal
penetration testing. Never put original customer records on public hosting.
