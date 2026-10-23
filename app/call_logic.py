"""Fixed greeting, CallRecorder (tool calls → database) and per-call cost estimate.

Nothing here needs LiveKit or API keys, so it is fully unit-tested.
"""

import json
from datetime import datetime
from pathlib import Path

from app.db import IST, now_ist

PRICING_PATH = Path(__file__).resolve().parent.parent / "data" / "pricing.json"

# Which outcome wins when a call records several (e.g. handover then end_call).
OUTCOME_PRIORITY = [
    "opted_out", "abusive", "wrong_number", "demo_booked", "handover", "callback",
    "interested", "not_interested", "voicemail", "no_answer", "call_dropped",
]
END_CALL_OUTCOMES = ("not_interested", "interested", "no_answer", "voicemail", "call_dropped")


def build_greeting(kb, lead=None, direction="outbound"):
    """The fixed opening line. Always discloses that the speaker is an AI."""
    biz = kb["business"]
    if direction == "inbound":
        return (f"ನಮಸ್ಕಾರ್ರೀ, {biz['name_kn']}ಗೆ ಕಾಲ್ ಮಾಡಿದ್ದಕ್ಕ ಧನ್ಯವಾದ. "
                "ನಾನು ಇಲ್ಲಿಯ AI ಅಸಿಸ್ಟೆಂಟ್. ಹೇಳ್ರಿ, ಏನು ಸಹಾಯ ಮಾಡ್ಲಿ?")
    name = (lead["name"] if lead and lead["name"] else "").strip()
    hello = f"ನಮಸ್ಕಾರ್ರೀ {name} ಅವರೇ." if name else "ನಮಸ್ಕಾರ್ರೀ."
    return (f"{hello} ನಾನು {biz['city_kn']}ದ {biz['name_kn']}ದ AI ಅಸಿಸ್ಟೆಂಟ್. "
            "ಈಗ ಎರಡು ನಿಮಿಷ ಮಾತಾಡಾಕ ತೊಂದರೆ ಆಗ್ತದೇನ್ರೀ?")


def call_context(db, lead=None, now=None, direction="outbound"):
    """Live facts appended to the instructions for this call."""
    now = (now or now_ist()).astimezone(IST)
    earliest = db.earliest_callback(now).astimezone(IST)
    lines = [
        "THIS CALL:",
        {"outbound": "- You called them.",
         "inbound": "- They called us. Thank them, find out what they need, then follow the same method.",
         "console": "- Test call from the console (Chetan is testing you); behave exactly as on a real call."}[direction],
        f"- Now: {now.strftime('%A %d %B %Y, %H:%M')} (India time).",
        f"- Earliest allowed callback: {earliest.strftime('%A %d %B, %H:%M')}. "
        "Pass callback times to schedule_callback as YYYY-MM-DDTHH:MM.",
    ]
    if lead:
        known = {k: lead[k] for k in ("name", "business", "business_type", "city") if lead[k]}
        if known:
            lines.append("- Lead details: " + ", ".join(f"{k}: {v}" for k, v in known.items()) + ".")
        if lead["attempts"] > 1:
            lines.append(f"- This is call attempt {lead['attempts']}; keep it especially brief.")
    return "\n".join(lines)


class CallRecorder:
    """Turns the agent's tool calls into database rows; one per call."""

    def __init__(self, db, phone, now=None, count_attempt=True):
        self.db = db
        self.started_at = now or now_ist()
        self.call_id, self.lead = db.start_call(phone, now=self.started_at, count_attempt=count_attempt)
        self.phone = self.lead["phone"] if self.lead else phone
        self.outcomes = []
        self.notes = []
        self.finished = False

    def _add(self, outcome, note=None):
        self.outcomes.append(outcome)
        if note:
            self.notes.append(f"{outcome}: {note}")

    @property
    def outcome(self):
        for o in OUTCOME_PRIORITY:
            if o in self.outcomes:
                return o
        return None

    def schedule_callback(self, when, note=None, now=None):
        """Returns None on success, or an error message for the agent to act on."""
        try:
            due = datetime.fromisoformat(when.strip())
        except (ValueError, AttributeError):
            return "Time not understood. Pass it as YYYY-MM-DDTHH:MM."
        if due.tzinfo is None:
            due = due.replace(tzinfo=IST)
        problem = self.db.check_callback_time(due, now=now)
        if problem:
            earliest = self.db.earliest_callback(now).astimezone(IST)
            return (f"Not allowed: a callback {problem}. Offer {earliest.strftime('%A %H:%M')} "
                    "or later instead, and ask the customer.")
        self.db.add_callback(self.call_id, self.phone, due, note, now=now)
        self._add("callback", f"{due.isoformat()} {note or ''}".strip())
        return None

    def record_opt_out(self, reason=None, abusive=False):
        self.db.opt_out(self.phone, reason)
        self._add("abusive" if abusive else "opted_out", reason)

    def request_handover(self, reason=None, preferred_time=None):
        self.db.add_handover(self.call_id, self.phone, reason, preferred_time)
        self._add("handover", reason)

    def book_demo(self, when, place=None, note=None):
        self.db.add_demo(self.call_id, self.phone, when, place, note)
        self._add("demo_booked", f"{when} {place or ''}".strip())

    def mark_wrong_number(self, note=None):
        self.db.conn.execute("UPDATE leads SET status = 'wrong_number' WHERE phone = ?", (self.phone,))
        self.db.conn.commit()
        self._add("wrong_number", note)

    def end_call(self, outcome="not_interested", note=None):
        self._add(outcome if outcome in END_CALL_OUTCOMES else "not_interested", note)

    def finish(self, usage=None, pricing=None, now=None):
        """Write the call row once. Returns the estimated cost (None if pricing is not filled in)."""
        if self.finished:
            return None
        self.finished = True
        cost = estimate_cost(usage, pricing) if usage else None
        self.db.finish_call(
            self.call_id, self.outcome or "call_dropped", "; ".join(self.notes) or None,
            usage, cost["total_inr"] if cost else None, now=now,
        )
        return cost


# ---- usage and cost ----

def summarize_usage(model_usage):
    """Flatten LiveKit's session.usage.model_usage into plain numbers."""
    out = {"llm_input_tokens": 0, "llm_cached_tokens": 0, "llm_output_tokens": 0,
           "stt_seconds": 0.0, "tts_characters": 0, "tts_seconds": 0.0, "models": []}
    for u in model_usage or []:
        kind = getattr(u, "type", "")
        out["models"].append(f"{kind}:{getattr(u, 'provider', '')}/{getattr(u, 'model', '')}")
        if kind == "llm_usage":
            out["llm_input_tokens"] += u.input_tokens
            out["llm_cached_tokens"] += u.input_cached_tokens
            out["llm_output_tokens"] += u.output_tokens
        elif kind == "stt_usage":
            out["stt_seconds"] += u.audio_duration
        elif kind == "tts_usage":
            out["tts_characters"] += u.characters_count
            out["tts_seconds"] += u.audio_duration
    return out


def load_pricing(path=PRICING_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def estimate_cost(usage, pricing=None):
    """Cost in ₹ from usage numbers and data/pricing.json. Parts without a price are left out."""
    pricing = pricing if pricing is not None else load_pricing()
    p = pricing.get("prices_inr", {})
    uncached = max(usage["llm_input_tokens"] - usage["llm_cached_tokens"], 0)
    parts = {
        "llm_input": _price(uncached / 1e6, p.get("llm_input_per_million_tokens")),
        "llm_cached_input": _price(usage["llm_cached_tokens"] / 1e6, p.get("llm_cached_input_per_million_tokens")),
        "llm_output": _price(usage["llm_output_tokens"] / 1e6, p.get("llm_output_per_million_tokens")),
        "stt": _price(usage["stt_seconds"] / 60, p.get("stt_per_minute")),
        "tts": _price(usage["tts_characters"] / 10_000, p.get("tts_per_10k_characters")),
        "telephony": _price(usage.get("call_seconds", 0) / 60, p.get("telephony_per_minute")),
    }
    known = {k: round(v, 4) for k, v in parts.items() if v is not None}
    return {
        "parts_inr": known,
        "missing_prices": sorted(k for k, v in parts.items() if v is None),
        "total_inr": round(sum(known.values()), 4) if known else None,
    }


def _price(quantity, rate):
    return quantity * rate if rate is not None else None
