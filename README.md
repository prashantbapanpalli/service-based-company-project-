# SourceCode Studio — AI Voice Sales Agent

A Kannada-first AI phone sales agent. See `CLAUDE.md` for the full project guide.

## Sales Trainer (step by step, Windows)

1. Open a terminal in this folder.
2. Start it: `python trainer.py`
3. Your browser opens http://localhost:8000 with five tabs:
   - **Call flow**: what to do at each stage of the call, collected from all the books
   - **Books**: 34 sales books from Indian, American, Chinese and European traditions, filterable by region
   - **Objection practice**: hear the objection, think of your reply, then reveal the recommended one
   - **Quiz**: scenario questions with explanations
   - **Agent instructions**: the exact text the voice agent receives, built from the playbook
4. Press `Ctrl+C` in the terminal to stop.

To teach the agent something new, edit `data/sales_playbook.json`, then run `python -m pytest tests -q`.
The agent picks up the change on the next call.
