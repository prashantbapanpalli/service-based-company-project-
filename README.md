# SourceCode Studio — AI Voice Sales Agent

A Kannada-first AI phone sales agent. See `CLAUDE.md` for the full project guide.

## Sales Trainer (step by step, Windows)

1. Open a terminal in this folder.
2. Start it: `python trainer.py`
3. Your browser opens http://localhost:8000 with six tabs:
   - **Call flow**: what to do at each stage of the call, collected from all the books
   - **Books**: 34 sales books from Indian, American, Chinese and European traditions, filterable by region
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
