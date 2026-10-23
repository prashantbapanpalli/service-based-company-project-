"""Calling rules, call recording and cost estimates (no LiveKit, no API keys)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.call_logic import CallRecorder, build_greeting, call_context, estimate_cost, summarize_usage
from app.db import IST, Database, normalize_phone
from app.knowledge import load_kb

PHONE = "+919876543210"
# A Tuesday at 11:00 India time, inside calling hours.
T0 = datetime(2026, 10, 20, 11, 0, tzinfo=IST)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "t.db", kb=load_kb())
    yield database
    database.close()


@pytest.mark.parametrize("raw, expected", [
    ("98765 43210", PHONE), ("+91-98765-43210", PHONE), ("09876543210", PHONE),
    ("919876543210", PHONE), ("0836-2441234", "+918362441234"), ("011-23456789", "+911123456789"),
    ("12345", None), ("0000000000", None), ("+1 415 555 0100", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_import_skips_invalid_duplicate_and_opted_out(db, tmp_path):
    db.opt_out("+91 99999 00000", "asked")
    csv_file = tmp_path / "leads.csv"
    csv_file.write_text("Phone,Name,Business\n9876543210,Ravi,Ravi Computers\n98765 43210,Dup,\n"
                        "12345,Bad,\n9999900000,Blocked,\n", encoding="utf-8")
    assert db.import_csv(csv_file) == {"added": 1, "invalid": 1, "opted_out": 1, "duplicate": 1}


def test_max_attempts_and_24_hour_gap(db):
    db.add_lead(PHONE, now=T0)
    t = T0
    for attempt in range(1, 4):
        assert db.next_lead(now=t)["phone"] == PHONE
        recorder = CallRecorder(db, PHONE, now=t)
        recorder.end_call("no_answer")
        recorder.finish(now=t + timedelta(minutes=1))
        assert db.get_lead(PHONE)["attempts"] == attempt
        if attempt < 3:
            assert "hours ago" in db.why_not_callable(db.get_lead(PHONE), now=t + timedelta(hours=23))
        t += timedelta(days=1)
    assert "max 3" in db.why_not_callable(db.get_lead(PHONE), now=t)
    assert db.next_lead(now=t) is None


def test_calling_hours(db):
    db.add_lead(PHONE, now=T0)
    assert db.next_lead(now=T0.replace(hour=9, minute=59)) is None
    assert db.next_lead(now=T0.replace(hour=10)) is not None
    assert db.next_lead(now=T0.replace(hour=19)) is None


def test_inbound_call_does_not_count_as_attempt(db):
    db.add_lead(PHONE, now=T0)
    CallRecorder(db, PHONE, now=T0, count_attempt=False)
    assert db.get_lead(PHONE)["attempts"] == 0


def test_callback_rules(db):
    db.add_lead(PHONE, now=T0)
    recorder = CallRecorder(db, PHONE, now=T0)
    assert "Not allowed" in recorder.schedule_callback("2026-10-20T18:00", now=T0)  # same day
    assert "Not allowed" in recorder.schedule_callback("2026-10-21T21:00", now=T0)  # after hours
    assert "not understood" in recorder.schedule_callback("tomorrow evening", now=T0)
    assert recorder.schedule_callback("2026-10-21T11:00", now=T0) is None
    recorder.finish(now=T0)
    lead = db.get_lead(PHONE)
    assert lead["status"] == "callback"
    assert db.next_lead(now=T0 + timedelta(hours=23, minutes=59)) is None
    assert db.next_lead(now=datetime(2026, 10, 21, 11, 0, tzinfo=IST))["phone"] == PHONE


def test_earliest_callback_moves_into_calling_hours(db):
    evening = T0.replace(hour=18, minute=30)  # +24h = 18:30 next day, still inside 10-19
    assert db.earliest_callback(evening) == evening + timedelta(days=1)
    late = datetime(2026, 10, 20, 20, 0, tzinfo=IST)  # +24h = 20:00 → next morning 10:00
    assert db.earliest_callback(late) == datetime(2026, 10, 22, 10, 0, tzinfo=IST)


def test_outcome_priority_and_abusive_opt_out(db):
    db.add_lead(PHONE, now=T0)
    recorder = CallRecorder(db, PHONE, now=T0)
    recorder.request_handover("price")
    recorder.end_call("not_interested")
    assert recorder.outcome == "handover"
    recorder.record_opt_out("swearing", abusive=True)
    assert recorder.outcome == "abusive"
    recorder.finish(now=T0)
    assert db.is_opted_out(PHONE) and db.get_lead(PHONE)["status"] == "opted_out"


def test_finish_writes_only_once(db):
    recorder = CallRecorder(db, "console", now=T0)
    recorder.finish(now=T0)
    recorder.finish(now=T0)
    assert db.report()["finished_calls"] == 1


def test_greeting_always_discloses_ai():
    kb = load_kb()
    for direction in ("outbound", "inbound", "console"):
        assert "AI" in build_greeting(kb, {"name": "Ravi"}, direction)
    assert "Ravi" in build_greeting(kb, {"name": "Ravi"})


def test_call_context_gives_date_and_earliest_callback(db):
    text = call_context(db, None, now=T0)
    assert "Tuesday 20 October 2026, 11:00" in text
    assert "Wednesday 21 October, 11:00" in text


def test_summarize_usage_and_cost():
    usage = summarize_usage([
        SimpleNamespace(type="llm_usage", provider="openai", model="m", input_tokens=2_000_000,
                        input_cached_tokens=1_000_000, output_tokens=100_000),
        SimpleNamespace(type="stt_usage", provider="sarvam", model="s", audio_duration=120.0),
        SimpleNamespace(type="tts_usage", provider="sarvam", model="t", characters_count=20_000, audio_duration=60.0),
    ])
    assert usage["llm_input_tokens"] == 2_000_000 and usage["stt_seconds"] == 120.0
    prices = {"prices_inr": {"llm_input_per_million_tokens": 10, "llm_cached_input_per_million_tokens": 2,
                             "llm_output_per_million_tokens": 40, "stt_per_minute": 1,
                             "tts_per_10k_characters": 5, "telephony_per_minute": None}}
    cost = estimate_cost(usage, prices)
    # 1M uncached*10 + 1M cached*2 + 0.1M*40 + 2 min*1 + 2*5 = 10+2+4+2+10
    assert cost["total_inr"] == 28
    assert cost["missing_prices"] == ["telephony"]


def test_cost_unknown_until_prices_are_filled():
    usage = summarize_usage([])
    assert estimate_cost(usage, {"prices_inr": {}})["total_inr"] is None


def test_sample_leads_are_never_called(db):
    db.add_lead(PHONE, source="sample (fake number)", now=T0)
    assert "sample" in db.why_not_callable(db.get_lead(PHONE), now=T0)
    assert db.next_lead(now=T0) is None


def test_manage_check_kb_passes():
    import manage
    assert manage.main(["check-kb"]) == 0
