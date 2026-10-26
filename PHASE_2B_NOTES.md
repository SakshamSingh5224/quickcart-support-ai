# Phase 2B — Conversational assistant

- Adds Streamlit chat messages, per-session conversational history, reset on order/ticket change, and short follow-up intent carryover.
- The **deterministic** `policy_engine.py` and `policy_audit.py` remain the source of truth for eligibility and financial amounts.
- Optional free Ollama `qwen2.5:0.5b` (runs on localhost only) supplies **additional wording**, never policy decisions. Disabled by default. The prompt excludes customer message, IDs, and CSV data. Some model completions may be rejected by a conservative output filter.
- Still a demo: draft JSON only, no real refunds, no identity verification, no persistence across browser sessions. Do not deploy with real customer data.
- Streamlit widget/state key collision is avoided: form key `order_lookup_form`; state key `active_ref`.

## Run

```bash
pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

## Optional local language model (Ubuntu)

Only install Ollama from its official documentation at https://ollama.com/download/linux after reviewing the installation steps. Once installed, in a **separate** terminal:

```bash
ollama pull qwen2.5:0.5b
ollama serve  # only if Ollama is not already running
```

Enable **Optional local Ollama explanations** in the app sidebar. If Ollama is stopped or the model missing, deterministic replies still work. No paid API is needed; Ollama is optional.

## Test with

Order `ORD-700002` → "My item arrived broken" → "What about that option?"; the existing historical refund + replacement must require review. Switch to a different order to verify chat reset. Create and download a support draft.
