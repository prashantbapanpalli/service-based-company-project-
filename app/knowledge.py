"""Builds the voice agent's instructions from the knowledge base and sales playbook.

Product facts come ONLY from data/knowledge_base.json. Sales *methods* come from
data/sales_playbook.json (summaries of classic sales books, in our own words).
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
KB_PATH = DATA_DIR / "knowledge_base.json"
PLAYBOOK_PATH = DATA_DIR / "sales_playbook.json"

STAGES = ("opening", "discovery", "value", "objection", "close", "follow_up", "mindset")
FORBIDDEN_WORDS = ("aadhaar", "otp", "password", "card number", "bank account")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_kb(path=KB_PATH):
    return load_json(path)


def load_playbook(path=PLAYBOOK_PATH):
    return load_json(path)


def check_playbook(playbook):
    """Return a list of problems; an empty list means the playbook is valid."""
    problems = []
    stage_ids = {s["id"] for s in playbook.get("stages", [])}
    if stage_ids != set(STAGES):
        problems.append(f"stages must be exactly {STAGES}, got {sorted(stage_ids)}")

    book_ids = set()
    for book in playbook.get("books", []):
        bid = book.get("id")
        if not bid or bid in book_ids:
            problems.append(f"missing or duplicate book id: {bid!r}")
        book_ids.add(bid)
        if not book.get("principles"):
            problems.append(f"book {bid} has no principles")
        for p in book.get("principles", []):
            if p.get("stage") not in STAGES:
                problems.append(f"book {bid}: unknown stage {p.get('stage')!r}")
            if not p.get("rule") or not p.get("on_our_call"):
                problems.append(f"book {bid}: principle needs 'rule' and 'on_our_call'")

    for o in playbook.get("objections", []):
        for b in o.get("books", []):
            if b not in book_ids:
                problems.append(f"objection {o.get('id')}: unknown book {b!r}")

    for i, q in enumerate(playbook.get("quiz", [])):
        if not 0 <= q.get("answer", -1) < len(q.get("options", [])):
            problems.append(f"quiz {i}: answer index out of range")
        for b in q.get("books", []):
            if b not in book_ids:
                problems.append(f"quiz {i}: unknown book {b!r}")

    for text in _spoken_lines(playbook):
        lowered = text.lower()
        for word in FORBIDDEN_WORDS:
            if word in lowered:
                problems.append(f"spoken line mentions {word!r}: {text}")
    return problems


def _spoken_lines(playbook):
    """Lines the agent might actually say (examples and objection responses)."""
    for book in playbook.get("books", []):
        for p in book.get("principles", []):
            for key in ("example_en", "example_kn"):
                if p.get(key):
                    yield p[key]
    for o in playbook.get("objections", []):
        for key in ("response_en", "response_kn"):
            if o.get(key):
                yield o[key]


def _product_section(kb):
    lines = []
    for p in kb["products"]:
        lines.append(f"- {p['name']}: {p['summary']}")
        lines.append(f"  Best for: {', '.join(p['good_for'])}.")
        lines.append(f"  Problems it solves: {'; '.join(p['pain_points'])}.")
        if p.get("price_approved"):
            lines.append(f"  Price: {p['price']}.")
        else:
            lines.append("  Price: NOT approved. Never say any number. Say Chetan will share it at the free demo.")
    return "\n".join(lines)


def _method_section(playbook):
    names = {s["id"]: s for s in playbook["stages"]}
    by_stage = {s: [] for s in STAGES}
    for book in playbook["books"]:
        for p in book["principles"]:
            by_stage[p["stage"]].append(f"  - {p['on_our_call']} ({book['title']})")
    parts = []
    for stage in STAGES:
        s = names[stage]
        parts.append(f"{s['name']}: {s['goal']}")
        parts.extend(by_stage[stage])
    return "\n".join(parts)


def _objection_section(playbook):
    lines = []
    for o in playbook["objections"]:
        lines.append(f"- If they say \"{o['objection_en']}\": {o['approach']}")
        if o.get("response_kn"):
            lines.append(f"  Example: {o['response_kn']}")
    return "\n".join(lines)


def build_instructions(kb=None, playbook=None):
    kb = kb if kb is not None else load_kb()
    playbook = playbook if playbook is not None else load_playbook()
    biz = kb["business"]
    offer = kb["offer"]
    excluded = "\n".join(f"- {t['tactic']}: {t['why']}" for t in playbook["excluded_tactics"])
    never = ", ".join(kb["never_ask_for"])

    return f"""You are an AI phone sales assistant for {biz['name']} ({biz['owner']}'s business in {biz['city']}).
You call {', '.join(biz['serves'])}.

IDENTITY: You are an AI. Always say so in the greeting and whenever asked. Offer a callback from {biz['owner']} if they prefer a human.

LANGUAGE: Speak natural spoken Kannada in Dharwad/Hubballi style. Short sentences. One question at a time. Never talk over the customer.

STYLE: A calm senior consultant in a premium boutique. Curious, tailored, never pushy. Understand first, then make ONE recommendation. Value before price. No fake urgency.

PRODUCTS (the only facts you may state):
{_product_section(kb)}

GOAL: Invite them to {offer['next_step']} ({offer['demo_length']}).

SALES METHOD, by call stage:
{_method_section(playbook)}

OBJECTIONS:
{_objection_section(playbook)}

NEVER USE THESE TACTICS:
{excluded}

HARD RULES:
- Never ask for {never}.
- If they say not to call again, confirm, apologise and end the call. This opt-out is permanent.
- If you do not know something, say {biz['owner']} will confirm it. Never invent facts, customers or numbers.
"""
