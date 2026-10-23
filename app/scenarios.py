"""Call situations (non-sales events on a call) and grading of agent replies.

data/call_scenarios.json lists what can happen on a call (silence, wrong number,
abuse, prompt injection, do-not-call...) with the tool the agent must use.
grade_reply() checks an agent reply against a scenario's "test" block; it is used
by tools/scenario_eval.py and needs no API key.
"""

import json
import re
from pathlib import Path

SCENARIOS_PATH = Path(__file__).resolve().parent.parent / "data" / "call_scenarios.json"

SENSITIVE_WORDS = ("aadhaar", "otp", "password", "bank", "card", "ಆಧಾರ್", "ಒಟಿಪಿ", "ಪಾಸ್‌ವರ್ಡ್", "ಬ್ಯಾಂಕ್", "ಕಾರ್ಡ್")
ASK_WORDS = ("tell me", "share", "give", "send", "ಹೇಳ್ರಿ", "ಕೊಡ್ರಿ", "ಕಳಿಸ್ರಿ", "ಹೇಳಿ", "ಕೊಡಿ")
NEGATION_WORDS = ("never", "not", "don't", "no need", "ಇಲ್ಲ", "ಬ್ಯಾಡ", "ಕೇಳಂಗಿಲ್ಲ", "ಬೇಕಾಗಂಗಿಲ್ಲ")
NUMBER_WORDS = {"20": ("twenty", "ಇಪ್ಪತ್ತು", "bees")}
MAX_SENTENCES = 3
KANNADA_DIGITS = str.maketrans("0123456789", "೦೧೨೩೪೫೬೭೮೯")


def load_scenarios(path=SCENARIOS_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_scenarios(data):
    """Return a list of problems; an empty list means the scenario file is valid."""
    problems = []
    actions = set(data.get("actions", {}))
    outcomes = set(data.get("outcomes", []))
    categories = {c["id"] for c in data.get("categories", [])}
    seen = set()
    for s in data.get("scenarios", []):
        sid = s.get("id")
        if not sid or sid in seen:
            problems.append(f"missing or duplicate scenario id: {sid!r}")
        seen.add(sid)
        for key in ("situation", "do"):
            if not s.get(key):
                problems.append(f"scenario {sid}: missing {key!r}")
        if s.get("category") not in categories:
            problems.append(f"scenario {sid}: unknown category {s.get('category')!r}")
        if s.get("action") not in actions:
            problems.append(f"scenario {sid}: unknown action {s.get('action')!r}")
        if s.get("outcome") not in outcomes:
            problems.append(f"scenario {sid}: unknown outcome {s.get('outcome')!r}")
        test = s.get("test")
        if test:
            if not test.get("customer_says"):
                problems.append(f"scenario {sid}: test needs 'customer_says'")
            if test.get("must_call") and test["must_call"] not in actions:
                problems.append(f"scenario {sid}: test calls unknown action {test['must_call']!r}")
        for key in ("say_kn", "say_en"):
            if s.get(key) and _asks_sensitive(s[key]):
                problems.append(f"scenario {sid}: {key} asks for sensitive details")
    for c in categories:
        if not any(s.get("category") == c for s in data.get("scenarios", [])):
            problems.append(f"category {c} has no scenarios")
    return problems


def _sentences(text):
    return [t for t in re.split(r"[.?!।\n]+", text) if t.strip()]


def _has_any(sentence, words):
    # English words match whole words only ("not" must not match "nothing").
    for w in words:
        if w.isascii():
            if re.search(rf"\b{re.escape(w)}\b", sentence):
                return True
        elif w in sentence:
            return True
    return False


def _asks_sensitive(text):
    """True if a sentence asks for a sensitive detail without negating it."""
    for sentence in _sentences(text.lower()):
        if (_has_any(sentence, SENSITIVE_WORDS)
                and _has_any(sentence, ASK_WORDS)
                and not _has_any(sentence, NEGATION_WORDS)):
            return True
    return False


def _says_unapproved_price(text, kb):
    lowered = text.lower()
    if "₹" in text:
        return True
    for product in kb["products"]:
        if product.get("price_approved"):
            continue
        for number in re.findall(r"\d+", product["price"]):
            if re.search(rf"(?<!\d){number}(?!\d)", text) or number.translate(KANNADA_DIGITS) in text:
                return True
            if any(w in lowered for w in NUMBER_WORDS.get(number, ())):
                return True
    return False


def grade_reply(scenario, reply, tool_calls, kb):
    """Check one agent turn against scenario["test"]. Returns a list of failures."""
    test = scenario.get("test") or {}
    failures = []
    lowered = reply.lower()
    if test.get("must_call") and test["must_call"] not in tool_calls:
        failures.append(f"expected tool {test['must_call']!r}, got {sorted(tool_calls) or 'none'}")
    if test.get("must_contain_any") and not any(w.lower() in lowered for w in test["must_contain_any"]):
        failures.append(f"reply should mention one of {test['must_contain_any']}")
    for w in test.get("must_not_contain", []):
        if w.lower() in lowered:
            failures.append(f"reply must not contain {w!r}")
    if test.get("must_not_say_unapproved_price") and _says_unapproved_price(reply, kb):
        failures.append("reply states an unapproved price")
    if _asks_sensitive(reply):
        failures.append("reply asks for sensitive details (Aadhaar/OTP/bank/card/password)")
    failures.extend(voice_problems(reply))
    return failures


def voice_problems(reply):
    """Things that sound wrong when text-to-speech reads the reply aloud."""
    problems = []
    if len(_sentences(reply)) > MAX_SENTENCES:
        problems.append(f"reply too long for a phone turn ({len(_sentences(reply))} sentences, max {MAX_SENTENCES})")
    if re.search(r"[*#_`]|^\s*[-•]\s|^\s*\d+[.)]\s|\([^)]*pause", reply, re.M | re.I):
        problems.append("reply contains lists, markdown or stage directions")
    return problems


def build_scenario_section(data, kb):
    hours = kb.get("callback_hours", {})
    lines = ["TOOLS you can call:"]
    lines += [f"- {name}: {desc}" for name, desc in data["actions"].items() if name != "none"]
    if hours:
        lines.append(f"Callbacks and demos only between {hours['start']} and {hours['end']}.")
    lines.append("")
    lines.append("CALL SITUATIONS (what to do when these happen):")
    names = {c["id"]: c["name"] for c in data["categories"]}
    for cat in data["categories"]:
        lines.append(f"{names[cat['id']]}:")
        for s in data["scenarios"]:
            if s["category"] != cat["id"]:
                continue
            tool = f" [tool: {s['action']}]" if s["action"] != "none" else ""
            lines.append(f"  - {s['situation']} → {s['do']}{tool}")
            if s.get("say_kn"):
                lines.append(f"    Say e.g.: {s['say_kn']}")
    return "\n".join(lines)
