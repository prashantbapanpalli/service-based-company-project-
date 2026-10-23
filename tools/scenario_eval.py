"""Test the agent's brain on every call situation that has a "test" block.

For each scenario, the LLM gets the real agent instructions, the fixed greeting
and the customer's line, then its reply and tool calls are graded
(app/scenarios.grade_reply). Run after changing the playbook, scenarios or model.

    python tools/scenario_eval.py              # all tests (needs OPENAI_API_KEY)
    python tools/scenario_eval.py wrong_number # one scenario
    python tools/scenario_eval.py --dry-run    # show what would be sent, no API call

Set OPENAI_MODEL to the same model agent.py uses (default below).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.call_logic import build_greeting  # noqa: E402
from app.knowledge import build_instructions, load_kb  # noqa: E402
from app.scenarios import grade_reply, load_scenarios  # noqa: E402

DEFAULT_MODEL = "gpt-4.1-mini"


def tool_specs(actions):
    return [{
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": {"details": {"type": "string"}}},
        },
    } for name, desc in actions.items() if name != "none"]


def load_env():
    env = Path(__file__).resolve().parent.parent / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def main(argv):
    dry_run = "--dry-run" in argv
    only = [a for a in argv if not a.startswith("--")]
    data = load_scenarios()
    kb = load_kb()
    tests = [s for s in data["scenarios"] if s.get("test") and (not only or s["id"] in only)]
    if not tests:
        print("No matching scenarios with a test block.")
        return 1

    instructions = build_instructions(kb=kb, scenarios=data)
    tools = tool_specs(data["actions"])
    if dry_run:
        print(f"Instructions: {len(instructions)} characters, {len(tools)} tools")
        for s in tests:
            print(f"- {s['id']}: customer says {s['test']['customer_says']!r}")
        return 0

    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (put it in .env). Use --dry-run to check without it.")
        return 1
    from openai import OpenAI

    client = OpenAI()
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    failed = 0
    for s in tests:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "assistant", "content": build_greeting(kb)},
                {"role": "user", "content": s["test"]["customer_says"]},
            ],
            tools=tools,
        )
        msg = response.choices[0].message
        reply = msg.content or ""
        calls = {c.function.name for c in (msg.tool_calls or [])}
        failures = grade_reply(s, reply, calls, kb)
        status = "PASS" if not failures else "FAIL"
        failed += bool(failures)
        print(f"[{status}] {s['id']}")
        print(f"   customer: {s['test']['customer_says']}")
        print(f"   agent:    {reply.strip() or '(no words)'}  tools={sorted(calls)}")
        for f in failures:
            print(f"   ✗ {f}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed with {model}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
