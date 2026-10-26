# QuickCart — Synthetic Public Demo

This is a **safe demonstration export** of a Python/Streamlit support chatbot and
operations dashboard. Its 36 orders and 28 tickets are entirely fabricated.
There are **no original case-study CSVs, customer messages, or Part 1 attachments** here.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.manage_users create --username quickadmin --role admin
python -m scripts.manage_users create --username supportagent --role agent
python -m scripts.manage_users create --username samplecustomer --role customer --customer-id CUST-DEMO-002
streamlit run app.py --server.address 127.0.0.1
```

Customer `CUST-DEMO-002` owns the synthetic `ORD-810002` and `TKT-910002`.
The ticket deliberately models a replacement/refund conflict for policy-audit demonstration.
This app does not issue real payments, courier changes, or vouchers.

## Streamlit Community Cloud

1. Upload **this folder only** to its **own GitHub repository** (not the original-data repo).
2. Deploy `app.py` from that repository at https://share.streamlit.io .
3. Provide **unique strong** passwords through your deployment's **App secrets**:

```toml
QC_PUBLIC_DEMO = "1"
QC_BOOTSTRAP_ADMIN_USER = "quickadmin"
QC_BOOTSTRAP_ADMIN_PASSWORD = "REPLACE_WITH_UNIQUE_STRONG_PASSWORD"
QC_BOOTSTRAP_AGENT_USER = "supportagent"
QC_BOOTSTRAP_AGENT_PASSWORD = "REPLACE_WITH_A_DIFFERENT_STRONG_PASSWORD"
QC_BOOTSTRAP_CUSTOMER_USER = "samplecustomer"
QC_BOOTSTRAP_CUSTOMER_PASSWORD = "REPLACE_WITH_ANOTHER_STRONG_PASSWORD"
QC_BOOTSTRAP_CUSTOMER_ID = "CUST-DEMO-002"
```

Never commit actual passwords, `.streamlit/secrets.toml`, or an `instance/` database.
Every cloud process may have an ephemeral SQLite database, so test account and support
request history can reset on restart/redeployment. This app is not a production secure
commerce service. Prefer an OIDC identity provider and persistent managed database for
anything beyond a portfolio demonstration.

## Tests

```bash
python -m pytest -q -m "not original_dataset"
python -m scripts.check_demo_safety .
```

See `PHASE_2E_NOTES.md` for architecture, limitations, and secure local setup.
