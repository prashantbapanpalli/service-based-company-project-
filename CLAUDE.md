# AI Voice Sales Agent — project guide for Claude Code

## What this is
A Kannada-first AI phone sales agent for **SourceCode Studio** (Chetan's business, Dharwad).
It sells two products to computer centres, cyber cafés and small businesses:
1. **Workflow Automation** — form-filling assistant (price ₹20/form, NOT yet approved — agent must not say it)
2. **AI Website Agent** — website with built-in AI chat assistant (custom quote)

Selling style: a senior consultant in a premium watch/suit boutique — calm, curious, tailored,
one recommendation, value before price, invite to a free demo. Never pushy, no fake urgency.

## Stack
LiveKit Agents 1.8 (Python) · Sarvam AI (STT `STTRealtime`, TTS `bulbul:v3`) · OpenAI LLM · SQLite.

## Layout
- `agent.py` — LiveKit voice agent: fixed AI-disclosure greeting, function tools, silence handling, max call time, cost logging
- `app/knowledge.py` — builds the agent's instructions from `data/knowledge_base.json` + `data/sales_playbook.json`
- `data/sales_playbook.json` — sales-book methods (own-words summaries) by call stage, objections, quiz, excluded tactics
- `trainer.py` + `web/index.html` — browser sales-training interface (`python trainer.py` → http://localhost:8000)
- `app/call_logic.py` — fixed greetings + `CallRecorder` (outcome → database), cost estimate
- `app/db.py` — SQLite: leads, calls, opt_outs, handovers, reports
- `manage.py` — CLI for leads (import, leads, next, optout, handovers, calls, report, export, check-kb)
- `tools/provider_test.py` — Kannada TTS/STT quality test
- `tools/render_demo.py` — renders `data/demo_call.json` to a WAV with Sarvam voices
- `tests/test_core.py` — pytest suite (no API keys needed)

## Commands (Windows, venv active: `.venv\Scripts\activate`)
- Tests: `python -m pytest tests -q`
- Sales trainer: `python trainer.py`
- Talk to the agent with the mic: `python agent.py console`
- Render demo audio: `python tools/render_demo.py`
- Leads: `python manage.py import data/sample_leads.csv`, `python manage.py report`

## Rules — do not break these
- The agent must always disclose it is an AI (greeting + when asked).
- Facts come ONLY from `data/knowledge_base.json`; prices are spoken only if `price_approved: true`.
- Opt-outs are permanent: blocked from calls and re-imports.
- Max 3 attempts per lead, never twice within 24 hours.
- Never ask for Aadhaar, bank, card, OTP or passwords.
- Kannada must be natural spoken Dharwad/Hubballi style, short sentences.
- Playbook = sales *methods* only; never copy book text, never add tactics listed in `excluded_tactics`.
- Never commit `.env`. Run the tests after every change.

## Roadmap
- Phase 1 (now): working Kannada prototype in console mode, measure real cost per call
- Phase 2: real phone number via SIP — INBOUND calls first. Outbound promotional calls in India
  need TRAI DLT registration, a 140-series number and DND scrubbing.
- Phase 3: sales intelligence + human handover · Phase 4: admin dashboard + WhatsApp follow-ups
- Phase 5: production hosting, monitoring, backups

## Owner
Chetan — final-year BCA student, prefers step-by-step concrete guidance.
