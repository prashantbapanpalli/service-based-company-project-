"""SQLite store for leads, calls, opt-outs, callbacks, demos and handovers.

The calling rules from CLAUDE.md are enforced here, not just in the prompt:
- opt-outs are permanent: never called again and skipped on re-import
- max attempts per lead (3) and never twice within 24 hours
- calls and callbacks only inside callback hours
"""

import csv
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "sales.db"
IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving

# Lead statuses that may still be called.
CALLABLE = ("new", "in_progress", "callback", "interested")

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT, business TEXT, business_type TEXT, city TEXT, source TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_called_at TEXT,
    next_call_after TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER REFERENCES leads(id),
    phone TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_s REAL,
    outcome TEXT,
    notes TEXT,
    usage_json TEXT,
    cost_inr REAL
);
CREATE TABLE IF NOT EXISTS opt_outs (
    phone TEXT PRIMARY KEY,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS callbacks (
    id INTEGER PRIMARY KEY, call_id INTEGER, lead_id INTEGER, phone TEXT NOT NULL,
    due_at TEXT NOT NULL, note TEXT, done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS demos (
    id INTEGER PRIMARY KEY, call_id INTEGER, lead_id INTEGER, phone TEXT NOT NULL,
    when_text TEXT NOT NULL, place TEXT, note TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handovers (
    id INTEGER PRIMARY KEY, call_id INTEGER, lead_id INTEGER, phone TEXT NOT NULL,
    reason TEXT, preferred_time TEXT, done INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
"""


def now_ist():
    return datetime.now(IST).replace(microsecond=0)


def _iso(dt):
    return dt.isoformat() if dt else None


def _parse(text):
    return datetime.fromisoformat(text) if text else None


def normalize_phone(raw):
    """Return an Indian number as +91 plus 10 digits, or None if it isn't one.

    Works for mobiles (98765 43210, 098765 43210) and landlines with STD code
    (0836-2441234 → +918362441234): both are 10 digits after the trunk 0.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] != "0":
        return "+91" + digits
    return None


def _clock(text):
    hour, minute = (int(x) for x in text.split(":"))
    return hour * 60 + minute


def within_hours(dt, hours):
    """True if dt (aware) falls inside {"start": "HH:MM", "end": "HH:MM"} in IST."""
    if not hours:
        return True
    local = dt.astimezone(IST)
    minutes = local.hour * 60 + local.minute
    return _clock(hours["start"]) <= minutes < _clock(hours["end"])


class Database:
    def __init__(self, path=DB_PATH, kb=None):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        kb = kb or {}
        rules = kb.get("call_rules", {})
        self.max_attempts = rules.get("max_attempts", 3)
        self.min_gap = timedelta(hours=rules.get("min_hours_between_calls", 24))
        self.hours = kb.get("callback_hours")

    def close(self):
        self.conn.close()

    # ---- leads ----

    def is_opted_out(self, phone):
        return self.conn.execute("SELECT 1 FROM opt_outs WHERE phone = ?", (phone,)).fetchone() is not None

    def add_lead(self, phone, name=None, business=None, business_type=None, city=None, source=None, now=None):
        """Add one lead. Returns 'added', 'invalid', 'opted_out' or 'duplicate'."""
        norm = normalize_phone(phone)
        if not norm:
            return "invalid"
        if self.is_opted_out(norm):
            return "opted_out"
        try:
            self.conn.execute(
                "INSERT INTO leads (phone, name, business, business_type, city, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (norm, name, business, business_type, city, source, _iso(now or now_ist())),
            )
        except sqlite3.IntegrityError:
            return "duplicate"
        self.conn.commit()
        return "added"

    def import_csv(self, path):
        """Import leads from a CSV with a 'phone' column. Returns counts per result."""
        counts = {"added": 0, "invalid": 0, "opted_out": 0, "duplicate": 0}
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                result = self.add_lead(
                    row.get("phone", ""), row.get("name") or None, row.get("business") or None,
                    row.get("business_type") or None, row.get("city") or None, row.get("source") or None,
                )
                counts[result] += 1
        return counts

    def get_lead(self, phone):
        return self.conn.execute("SELECT * FROM leads WHERE phone = ?", (normalize_phone(phone) or phone,)).fetchone()

    def leads(self, status=None):
        if status:
            return self.conn.execute("SELECT * FROM leads WHERE status = ? ORDER BY id", (status,)).fetchall()
        return self.conn.execute("SELECT * FROM leads ORDER BY id").fetchall()

    def why_not_callable(self, lead, now=None):
        """None if the lead may be called now, otherwise the reason it may not."""
        now = now or now_ist()
        if (lead["source"] or "").lower().startswith("sample"):
            return "sample lead (fake number), never called"
        if self.is_opted_out(lead["phone"]):
            return "opted out (permanent)"
        if lead["status"] not in CALLABLE:
            return f"status is {lead['status']}"
        if lead["attempts"] >= self.max_attempts:
            return f"already called {lead['attempts']} times (max {self.max_attempts})"
        last = _parse(lead["last_called_at"])
        if last and now - last < self.min_gap:
            return f"called less than {int(self.min_gap.total_seconds() // 3600)} hours ago"
        after = _parse(lead["next_call_after"])
        if after and now < after:
            return f"callback scheduled for {after.strftime('%d %b %H:%M')}"
        if not within_hours(now, self.hours):
            return f"outside calling hours {self.hours['start']}-{self.hours['end']}"
        return None

    def next_lead(self, now=None):
        """The next lead that may be called now, or None."""
        for lead in self.conn.execute(
            f"SELECT * FROM leads WHERE status IN ({','.join('?' * len(CALLABLE))}) "
            "ORDER BY COALESCE(next_call_after, created_at), id", CALLABLE,
        ):
            if self.why_not_callable(lead, now) is None:
                return lead
        return None

    # ---- calls ----

    def start_call(self, phone, now=None, count_attempt=True):
        """Record the start of a call. Outbound calls count as an attempt. Returns (call_id, lead or None)."""
        now = now or now_ist()
        norm = normalize_phone(phone) or phone
        lead = self.get_lead(norm)
        if lead and count_attempt:
            self.conn.execute(
                "UPDATE leads SET attempts = attempts + 1, last_called_at = ?, "
                "status = CASE WHEN status = 'new' THEN 'in_progress' ELSE status END WHERE id = ?",
                (_iso(now), lead["id"]),
            )
        cur = self.conn.execute(
            "INSERT INTO calls (lead_id, phone, started_at) VALUES (?, ?, ?)",
            (lead["id"] if lead else None, norm, _iso(now)),
        )
        self.conn.commit()
        return cur.lastrowid, self.get_lead(norm)

    def earliest_callback(self, now=None):
        """Earliest allowed callback time after a call made now."""
        now = now or now_ist()
        earliest = now + self.min_gap
        if self.hours and not within_hours(earliest, self.hours):
            day = earliest.astimezone(IST)
            start = _clock(self.hours["start"])
            if day.hour * 60 + day.minute >= _clock(self.hours["end"]):
                day += timedelta(days=1)
            earliest = day.replace(hour=start // 60, minute=start % 60, second=0)
        return earliest

    def check_callback_time(self, when, now=None):
        """None if a callback at `when` is allowed, otherwise the reason."""
        now = now or now_ist()
        if when < now + self.min_gap:
            return f"must be at least {int(self.min_gap.total_seconds() // 3600)} hours from now"
        if not within_hours(when, self.hours):
            return f"must be between {self.hours['start']} and {self.hours['end']}"
        return None

    def add_callback(self, call_id, phone, due_at, note=None, now=None):
        lead = self.get_lead(phone)
        self.conn.execute(
            "INSERT INTO callbacks (call_id, lead_id, phone, due_at, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (call_id, lead["id"] if lead else None, phone, _iso(due_at), note, _iso(now or now_ist())),
        )
        if lead:
            self.conn.execute("UPDATE leads SET next_call_after = ? WHERE id = ?", (_iso(due_at), lead["id"]))
        self.conn.commit()

    def add_demo(self, call_id, phone, when_text, place=None, note=None, now=None):
        lead = self.get_lead(phone)
        self.conn.execute(
            "INSERT INTO demos (call_id, lead_id, phone, when_text, place, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (call_id, lead["id"] if lead else None, phone, when_text, place, note, _iso(now or now_ist())),
        )
        self.conn.commit()

    def add_handover(self, call_id, phone, reason=None, preferred_time=None, now=None):
        lead = self.get_lead(phone)
        self.conn.execute(
            "INSERT INTO handovers (call_id, lead_id, phone, reason, preferred_time, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (call_id, lead["id"] if lead else None, phone, reason, preferred_time, _iso(now or now_ist())),
        )
        self.conn.commit()

    def opt_out(self, phone, reason=None, now=None):
        norm = normalize_phone(phone) or phone
        self.conn.execute(
            "INSERT OR IGNORE INTO opt_outs (phone, reason, created_at) VALUES (?, ?, ?)",
            (norm, reason, _iso(now or now_ist())),
        )
        self.conn.execute("UPDATE leads SET status = 'opted_out' WHERE phone = ?", (norm,))
        self.conn.commit()

    def finish_call(self, call_id, outcome, notes=None, usage=None, cost_inr=None, now=None):
        now = now or now_ist()
        call = self.conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        duration = (now - _parse(call["started_at"])).total_seconds()
        self.conn.execute(
            "UPDATE calls SET ended_at = ?, duration_s = ?, outcome = ?, notes = ?, usage_json = ?, cost_inr = ? WHERE id = ?",
            (_iso(now), duration, outcome, notes, json.dumps(usage) if usage else None, cost_inr, call_id),
        )
        status = LEAD_STATUS_BY_OUTCOME.get(outcome)
        if call["lead_id"] and status:
            self.conn.execute(
                "UPDATE leads SET status = ? WHERE id = ? AND status != 'opted_out'", (status, call["lead_id"])
            )
        self.conn.commit()

    # ---- reports ----

    def pending(self, table):
        return self.conn.execute(f"SELECT * FROM {table} WHERE done = 0 ORDER BY id").fetchall()

    def mark_done(self, table, row_id):
        self.conn.execute(f"UPDATE {table} SET done = 1 WHERE id = ?", (row_id,))
        self.conn.commit()

    def recent_calls(self, limit=20):
        return self.conn.execute("SELECT * FROM calls ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def report(self):
        q = self.conn.execute
        outcomes = dict(q("SELECT COALESCE(outcome, 'unfinished'), COUNT(*) FROM calls GROUP BY 1").fetchall())
        statuses = dict(q("SELECT status, COUNT(*) FROM leads GROUP BY status").fetchall())
        row = q("SELECT COUNT(*), AVG(duration_s), SUM(cost_inr), COUNT(cost_inr) FROM calls WHERE ended_at IS NOT NULL").fetchone()
        return {
            "leads": statuses,
            "calls": outcomes,
            "finished_calls": row[0],
            "avg_duration_s": round(row[1], 1) if row[1] else None,
            "total_cost_inr": round(row[2], 2) if row[3] else None,
            "avg_cost_inr": round(row[2] / row[3], 2) if row[3] else None,
            "opt_outs": q("SELECT COUNT(*) FROM opt_outs").fetchone()[0],
            "pending_callbacks": q("SELECT COUNT(*) FROM callbacks WHERE done = 0").fetchone()[0],
            "pending_handovers": q("SELECT COUNT(*) FROM handovers WHERE done = 0").fetchone()[0],
            "demos": q("SELECT COUNT(*) FROM demos").fetchone()[0],
        }


LEAD_STATUS_BY_OUTCOME = {
    "demo_booked": "demo_booked",
    "callback": "callback",
    "interested": "interested",
    "not_interested": "not_interested",
    "opted_out": "opted_out",
    "abusive": "opted_out",
    "wrong_number": "wrong_number",
    "handover": "handover",
    # no_answer, voicemail, call_dropped: status unchanged, retried within the attempt limit
}
