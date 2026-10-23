# SourceCode Studio — AI Voice Sales Agent

A Kannada-first AI phone sales agent. See `CLAUDE.md` for the full project guide.

## Talk to the agent (step by step, Windows)

1. `python -m venv .venv` then `.venv\Scripts\activate`
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `SARVAM_API_KEY`.
4. `python agent.py download-files` (once)
5. Speak to it: `python agent.py console`, or type instead: `python agent.py console --text`
6. After the call: `python manage.py calls` shows the outcome, `python manage.py report` the totals.
   Fill in `data/pricing.json` from your providers' price pages to see the cost per call in ₹.

Warnings about `LIVEKIT_API_KEY` in console mode are harmless (optional cloud features).

## Leads

`python manage.py import data/sample_leads.csv` (sample numbers are never called),
`python manage.py next`, `python manage.py check 98450 00001`, `python manage.py optout <number>`,
`python manage.py handovers` (people Chetan must call back). Run `python manage.py -h` for all commands.

## Sales Trainer (step by step, Windows)

1. Open a terminal in this folder.
2. Start it: `python trainer.py`
3. Your browser opens http://localhost:8000 with six tabs:
   - **Call flow**: what to do at each stage of the call, collected from all the books
   - **Books**: 40 sales books from Indian, American, Chinese, European and Kannada traditions, filterable by region
   - **Objection practice**: hear the objection, think of your reply, then reveal the recommended one
   - **Call situations**: 46 things that can happen on a call (silence, wrong number, angry caller, scam fear, someone reading out their OTP, "ignore your instructions", do-not-call…) with what to do and say; tick *Practice mode* to quiz yourself
   - **Quiz**: scenario questions with explanations
   - **Agent instructions**: the exact text the voice agent receives, built from the playbook
4. Press `Ctrl+C` in the terminal to stop.

To teach the agent something new, edit `data/sales_playbook.json`, then run `python -m pytest tests -q`.
The agent picks up the change on the next call.

## Testing the agent on every call situation

1. Put your key in `.env`: `OPENAI_API_KEY=...` (and `OPENAI_MODEL=` the model agent.py uses).
2. Run `python tools/scenario_eval.py`. It plays the customer's line for each auto-tested
   situation and checks the reply: right tool used (opt-out, callback, handover, demo),
   no unapproved price, never asks for Aadhaar/OTP/bank details, admits being an AI.
3. If something fails, improve the matching entry in `data/call_scenarios.json` and run again.
