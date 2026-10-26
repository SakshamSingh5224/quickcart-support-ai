# Phase 2C — SQLite ticket management and local agent review

## What's implemented

- **Persistent local requests:** Every submitted request is stored under `instance/quickcart.sqlite3`, independently from the immutable Part 1 CSVs.
- **Idempotent submissions:** Each chat turn gets a UUID token; submitting the same turn twice returns the same record rather than creating duplicates. Reusing a token with changed content is rejected.
- **Administrative workflow:** `SUBMITTED → IN_REVIEW → FOLLOW_UP_APPROVED → CLOSED` or a rejection route (`SUBMITTED/IN_REVIEW → REJECTED → CLOSED`). No `PAID`, `REFUNDED`, `REPLACEMENT_SENT`, or similar payment state exists.
- **Event history:** Every creation and status change is stored transactionally with timestamp, previous/new status, reviewer label, and required note. Stale concurrent updates are rejected.
- **Local demo agent queue:** Streamlit sidebar → **Agent queue** → filter requests → select a request → enter a reviewer label and required note → save a status change.
- **Historical policy protection:** The policy engine retains authority, and a request with reconciliation needed cannot contain positive new cash/voucher suggestions.
- **No external transactions:** `FOLLOW_UP_APPROVED` only marks approval for **administrative follow-up**; it is not permission to issue money or make a replacement.

## SQLite tables

- `support_requests`: one row per new Phase 2C support request with order reference, policy decision snapshot, suggested action, review flags, status and reviewer note.
- `request_events`: immutable append-only transition events per request. (The prototype never exposes delete/edit events through the UI.)

The source `data/orders_clean.csv` and `data/support_tickets_clean.csv` remain **historical read-only CSVs**, not writable tables. New requests are in SQLite and do not overwrite any historical support ticket.

## Installation (Ubuntu, existing repository)

```bash
cd ~/Desktop
cp -a quickcart-support-ai quickcart-phase2b-backup
unzip -o ~/Downloads/quickcart-phase2c.zip -d ~/Desktop
cd ~/Desktop/quickcart-support-ai
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
streamlit run app.py --server.address 127.0.0.1
```

If `.venv` does not exist, use `python3 -m venv .venv` first. Access `http://127.0.0.1:8501` on the same computer.

The database is created automatically at `instance/quickcart.sqlite3` on first app launch. **Do not delete `instance/`** if you want to retain submitted tickets. The directory is deliberately Git-ignored. For a local backup, stop Streamlit and copy the `instance/` directory to a secure backup location.

## Acceptance test: ORD-700002

1. In **Customer help**, load `ORD-700002`.
2. Ask: `My item arrived broken. Can I get a refund?`
3. Confirm you see a historical Rule 2 replacement + recorded ₹799 refund conflict, and **Request historical resolution review** (not an automated cash refund).
4. Click **Submit local support request**. You should receive a `QC-...` ID and status `SUBMITTED`.
5. Select **Agent queue** in the sidebar. Locate the request; select it and review the policy snapshot and audit entry.
6. Enter reviewer label `demo-agent`, note `Historical payout and replacement need reconciliation`, and set status to `IN_REVIEW`.
7. Optionally select `FOLLOW_UP_APPROVED`, clearly meaning *administrative follow-up only*, then `CLOSED`, with notes for each transition.
8. Refresh/restart Streamlit and verify the request and event history remain available.
9. Run `python -m pytest -q` (release verification: **59 passed**, including real cleaned-dataset integration).

## Deployment and privacy boundaries

- **Do not publish or deploy with real customer CSVs.** An order/ticket ID is not proof of ownership; even the 'Agent queue' is unprotected. Use localhost and approved/synthetic data only.
- Customer questions and reviewer notes are stored in plaintext SQLite. They can contain sensitive data. Keep the database private, restrict local filesystem access, and exclude it from Git.
- Approval is a demo *workflow status*. Actual payment or replacement requires a separate authenticated staff process and payment systems with reconciliation, idempotency and audit controls.
- The project does not use a real ticketing provider or send customer notices. Original historical CSV tickets do not become editable.
- New SQLite requests are not tied to verified customer identities and cannot be deployed as-is. Authentication and authorization are planned for later phases.
- Optional Ollama language-model text remains supplemental, and the Python policy engine makes all refund/voucher decisions.

## Files added and updated

- **New:** `ticket_store.py`, `tests/test_ticket_store.py`, `tests/test_phase2c_integration.py`, `PHASE_2C_NOTES.md`.
- **Updated:** `app.py` (customer + agent workspaces), `.gitignore` (SQLite files), `README.md`.
- **Preserved:** `conversation.py`, `policy_engine.py`, `policy_audit.py`, `part1/`, `data/`, and all earlier tests.

## GitHub

After validating locally, run:

```bash
cd ~/Desktop/quickcart-support-ai
git status
git add app.py ticket_store.py tests/ PHASE_2C_NOTES.md README.md .gitignore
git commit -m "Phase 2C: persist support requests and add agent review workflow"
git push origin main
```

Check that `instance/quickcart.sqlite3` is not staged. Keep the repository **private** unless the included CSVs and customer text are explicitly approved for public distribution.
