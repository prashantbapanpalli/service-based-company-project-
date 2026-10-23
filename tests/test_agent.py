"""Runs the real SalesAgent and its tools inside a LiveKit AgentSession.

A scripted LLM stands in for OpenAI, so no API key is needed: it maps the
customer's line to the tool call a good agent should make. These tests check
the wiring (tool → database rows, hang-up, rule enforcement), not the model.
"""

import asyncio
import json

import pytest

pytest.importorskip("livekit.agents")

from livekit.agents import AgentSession  # noqa: E402
from livekit.agents.llm import LLM, ChatChunk, ChoiceDelta, FunctionToolCall, LLMStream  # noqa: E402
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS  # noqa: E402

from agent import SalesAgent  # noqa: E402
from app.call_logic import CallRecorder  # noqa: E402
from app.db import Database, now_ist  # noqa: E402
from app.knowledge import build_instructions, load_kb  # noqa: E402
from app.scenarios import load_scenarios  # noqa: E402

PHONE = "+919876543210"


class ScriptedLLM(LLM):
    """Replies from a script: {customer line: (text, [(tool, args)])}; tool outputs get a goodbye."""

    def __init__(self, script):
        super().__init__()
        self.script = script

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        return ScriptedStream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class ScriptedStream(LLMStream):
    async def _run(self):
        last = self.chat_ctx.items[-1]
        if last.type == "function_call_output":
            text, calls = "ಧನ್ಯವಾದರೀ, ನಮಸ್ಕಾರ.", []
        else:
            text, calls = self._llm.script.get(last.text_content, ("ಆಗ್ಲಿರೀ.", []))
        self._event_ch.send_nowait(ChatChunk(id="1", delta=ChoiceDelta(role="assistant", content=text)))
        tool_calls = [
            FunctionToolCall(name=name, arguments=json.dumps(args), call_id=f"c{i}")
            for i, (name, args) in enumerate(calls)
        ]
        if tool_calls:
            self._event_ch.send_nowait(ChatChunk(id="1", delta=ChoiceDelta(role="assistant", tool_calls=tool_calls)))


@pytest.fixture
def db(tmp_path):
    kb = load_kb()
    database = Database(tmp_path / "test.db", kb=kb)
    database.add_lead(PHONE, name="Ravi", business="Ravi Computers", business_type="computer centre")
    yield database
    database.close()


async def run_turn(db, script, line):
    recorder = CallRecorder(db, PHONE)
    agent = SalesAgent(recorder=recorder, instructions=build_instructions(), greeting="ನಮಸ್ಕಾರ್ರೀ.")
    session = AgentSession(llm=ScriptedLLM(script))
    await session.start(agent)
    result = await session.run(user_input=line)
    await asyncio.sleep(0.1)  # let hang-up callbacks run
    return recorder, result, session


def test_agent_tools_match_scenario_actions():
    tools = {name for name in dir(SalesAgent) if not name.startswith("_")}
    actions = set(load_scenarios()["actions"]) - {"none"}
    assert actions <= tools, actions - tools


async def test_opt_out_is_permanent_and_hangs_up(db):
    line = "ಮತ್ತ ಕಾಲ್ ಮಾಡಬ್ಯಾಡ್ರಿ."
    recorder, result, session = await run_turn(db, {line: ("ಆಗ್ಲಿರೀ.", [("record_opt_out", {"reason": line})])}, line)
    result.expect.contains_function_call(name="record_opt_out")
    assert db.is_opted_out(PHONE)
    recorder.finish()
    assert db.get_lead(PHONE)["status"] == "opted_out"
    assert db.add_lead(PHONE) == "opted_out"  # re-import is blocked
    assert db.next_lead() is None


async def test_callback_too_soon_is_refused_then_allowed(db):
    soon = (now_ist()).strftime("%Y-%m-%dT%H:%M")
    later = db.earliest_callback().strftime("%Y-%m-%dT%H:%M")
    script = {
        "ಇವತ್ತು ಸಂಜಿ ಕಾಲ್ ಮಾಡ್ರಿ.": ("ಆಗ್ಲಿರೀ.", [("schedule_callback", {"when": soon})]),
        "ಸರಿ, ಆ ಟೈಮ್ ಆಗ್ತದ.": ("ಸರಿರೀ.", [("schedule_callback", {"when": later})]),
    }
    recorder, result, session = await run_turn(db, script, "ಇವತ್ತು ಸಂಜಿ ಕಾಲ್ ಮಾಡ್ರಿ.")
    output = next(e.item for e in result.events if e.type == "function_call_output")
    assert "Not allowed" in output.output
    assert db.pending("callbacks") == []

    result = await session.run(user_input="ಸರಿ, ಆ ಟೈಮ್ ಆಗ್ತದ.")
    assert len(db.pending("callbacks")) == 1
    recorder.finish()
    assert db.get_lead(PHONE)["status"] == "callback"


async def test_demo_and_handover_are_saved(db):
    line = "ನಾಳೆ ಹನ್ನೊಂದಕ್ಕ ಡೆಮೋ ತೋರಿಸ್ರಿ, ರೇಟು ಚೇತನ್ ಹೇಳಲಿ."
    script = {line: ("ಸರಿರೀ.", [
        ("book_demo", {"when": "tomorrow 11 am", "place": "their centre"}),
        ("request_handover", {"reason": "wants the price from Chetan"}),
    ])}
    recorder, result, session = await run_turn(db, script, line)
    assert db.conn.execute("SELECT COUNT(*) FROM demos").fetchone()[0] == 1
    assert len(db.pending("handovers")) == 1
    recorder.finish(usage={"llm_input_tokens": 1000, "llm_cached_tokens": 0, "llm_output_tokens": 50,
                           "stt_seconds": 30.0, "tts_characters": 200, "tts_seconds": 10.0})
    call = db.recent_calls(1)[0]
    assert call["outcome"] == "demo_booked"  # demo outranks handover
    assert json.loads(call["usage_json"])["llm_input_tokens"] == 1000


async def test_wrong_number_closes_lead_and_session(db):
    line = "ಇದು ಮನಿ ನಂಬರ್ ರೀ."
    recorder, result, session = await run_turn(db, {line: ("ಕ್ಷಮಿಸ್ರಿ.", [("mark_wrong_number", {})])}, line)
    recorder.finish()
    assert db.get_lead(PHONE)["status"] == "wrong_number"
    assert db.next_lead() is None
