"""SourceCode Studio Kannada voice sales agent (LiveKit Agents 1.8).

    python agent.py console      talk to it with your microphone (no phone needed)
    python agent.py dev          run as a worker for LiveKit (inbound SIP calls)

Pipeline: Sarvam STTRealtime (kn-IN, codemix) → OpenAI LLM → Sarvam TTS bulbul:v3.
Instructions come from app/knowledge.py; every tool call is written to SQLite
by app/call_logic.CallRecorder, and token/audio usage is logged per call.

Outbound dialling is OFF unless ALLOW_OUTBOUND=1: promotional calls in India
need TRAI DLT registration, a 140-series number and DND scrubbing first.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Literal

from livekit import api, rtc
from livekit.agents import AMD, Agent, AgentServer, AgentSession, JobContext, JobProcess, RunContext, cli, function_tool
from livekit.plugins import openai, sarvam, silero

from app.call_logic import CallRecorder, build_greeting, call_context, load_pricing, summarize_usage
from app.db import Database, normalize_phone, now_ist
from app.knowledge import build_instructions, build_stt_prompt, load_kb

logger = logging.getLogger("sales-agent")

ROOT = Path(__file__).resolve().parent
GOODBYE_KN = "ಧನ್ಯವಾದರೀ. ನಮಸ್ಕಾರ."
DEFAULT_LLM = "gpt-4.1-mini"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def hang_up_after(handle, session):
    """Close the session once this speech (e.g. the goodbye) has finished playing."""
    handle.add_done_callback(lambda _: session.shutdown())


class SalesAgent(Agent):
    def __init__(self, *, recorder: CallRecorder, instructions: str, greeting: str, greet_on_enter: bool = True) -> None:
        super().__init__(instructions=instructions)
        self.recorder = recorder
        self.greeting = greeting
        self.greet_on_enter = greet_on_enter

    async def on_enter(self) -> None:
        # Outbound calls greet only after voicemail detection confirms a person answered.
        if self.greet_on_enter:
            self.greet()

    def greet(self) -> None:
        # Fixed, pre-written greeting with the AI disclosure, never LLM-generated.
        if self.session.tts is not None:
            self.session.say(self.greeting)

    @function_tool
    async def end_call(
        self,
        ctx: RunContext,
        outcome: Literal["not_interested", "interested", "no_answer", "voicemail", "call_dropped"] = "not_interested",
        note: str = "",
    ) -> str:
        """End the call after a short goodbye. Use when the customer says bye, after an agreed next step
        has been confirmed, for voicemail or IVR, or when the customer is in grief or an emergency.

        Args:
            outcome: How the call ended if no demo, callback, handover or opt-out was recorded.
            note: One short line about the call for Chetan.
        """
        self.recorder.end_call(outcome, note or None)
        hang_up_after(ctx.speech_handle, ctx.session)
        return "Say one short, warm goodbye now, then stop."

    @function_tool
    async def schedule_callback(self, ctx: RunContext, when: str, note: str = "") -> str:
        """Record a callback time the customer agreed to.

        Args:
            when: Local India time as YYYY-MM-DDTHH:MM. Must be at least 24 hours from now and within callback hours.
            note: What to talk about next time.
        """
        problem = self.recorder.schedule_callback(when, note or None)
        if problem:
            return problem
        return "Callback saved. Confirm the day and time once in words, then end the call."

    @function_tool
    async def record_opt_out(self, ctx: RunContext, reason: str = "", abusive: bool = False) -> str:
        """Permanently stop all calls to this number. Use for any 'don't call', 'remove my number', DND,
        or abusive caller. Never try to persuade before calling this.

        Args:
            reason: The customer's words, briefly.
            abusive: True if the caller was abusive or threatening.
        """
        self.recorder.record_opt_out(reason or None, abusive=abusive)
        hang_up_after(ctx.speech_handle, ctx.session)
        return "Number removed. Confirm they will not be called again, apologise briefly, say goodbye."

    @function_tool
    async def request_handover(self, ctx: RunContext, reason: str, preferred_time: str = "") -> str:
        """Ask Chetan to call this person himself: they want a human, a price you may not say,
        a question not in the knowledge base, another service, or an existing-customer issue.

        Args:
            reason: What Chetan needs to know, in one line.
            preferred_time: When they would like Chetan to call, in their words.
        """
        self.recorder.request_handover(reason, preferred_time or None)
        return "Saved for Chetan. Tell the customer Chetan will call them, confirm the time if given."

    @function_tool
    async def book_demo(self, ctx: RunContext, when: str, place: str = "", note: str = "") -> str:
        """Record a free demo the customer agreed to.

        Args:
            when: Day and time, e.g. 'Thursday 11 am' or YYYY-MM-DDTHH:MM.
            place: 'their centre' with the address if given, or 'video call'.
            note: Which product interests them and why.
        """
        self.recorder.book_demo(when, place or None, note or None)
        return "Demo saved. Repeat the day, time and place once, thank them, then end the call."

    @function_tool
    async def mark_wrong_number(self, ctx: RunContext, note: str = "") -> str:
        """The number does not belong to a business we meant to call. Never pitch; apologise and end.

        Args:
            note: Who answered, briefly.
        """
        self.recorder.mark_wrong_number(note or None)
        hang_up_after(ctx.speech_handle, ctx.session)
        return "Apologise for the wrong number in one sentence and say goodbye."


def build_session(kb, vad) -> AgentSession:
    rules = kb.get("call_rules", {})
    llm = openai.LLM(model=os.environ.get("OPENAI_MODEL", DEFAULT_LLM))
    return AgentSession(
        stt=sarvam.STTRealtime(language="kn-IN", mode="codemix", prompt=build_stt_prompt(kb)),
        llm=llm,
        tts=sarvam.TTS(
            target_language_code="kn-IN",
            model="bulbul:v3",
            speaker=os.environ.get("SARVAM_SPEAKER") or None,
        ),
        vad=vad,
        user_away_timeout=rules.get("silence_timeout_seconds", 8),
        # Safety net for the VOICE RULES: strip markdown and emoji before speech.
        tts_text_transforms=["filter_markdown", "filter_emoji"],
    )


def find_sip_caller(room: rtc.Room):
    for p in room.remote_participants.values():
        if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return p
    return None


def prewarm(proc: JobProcess) -> None:
    # Load the voice-activity model once per process, not inside each call.
    proc.userdata["vad"] = silero.VAD.load()


load_env()
server = AgentServer()
server.setup_fnc = prewarm


@server.rtc_session(agent_name="sourcecode-sales")
async def entrypoint(ctx: JobContext) -> None:
    kb = load_kb()
    db = Database(kb=kb)
    rules = kb.get("call_rules", {})
    meta = json.loads(ctx.job.metadata or "{}")

    outbound_phone = normalize_phone(meta.get("phone", ""))
    if outbound_phone:
        if os.environ.get("ALLOW_OUTBOUND") != "1" or not os.environ.get("SIP_OUTBOUND_TRUNK_ID"):
            logger.error("outbound call refused: set ALLOW_OUTBOUND=1 and SIP_OUTBOUND_TRUNK_ID (after DLT registration)")
            db.close()
            ctx.shutdown("outbound disabled")
            return
        lead = db.get_lead(outbound_phone)
        reason = "not in the leads list" if lead is None else db.why_not_callable(lead)
        if reason:
            logger.warning(f"not calling {outbound_phone}: {reason}")
            db.close()
            ctx.shutdown(reason)
            return
        phone, direction = outbound_phone, "outbound"
    elif ctx.is_fake_job():
        phone, direction = "console", "console"
    else:
        await ctx.connect()
        caller = find_sip_caller(ctx.room) or await ctx.wait_for_participant()
        sip_number = caller.attributes.get("sip.phoneNumber", "")
        phone = normalize_phone(sip_number) or sip_number or caller.identity
        direction = "inbound"

    recorder = CallRecorder(db, phone, count_attempt=(direction == "outbound"))
    instructions = build_instructions(kb=kb) + "\n\n" + call_context(db, recorder.lead, direction=direction)
    agent = SalesAgent(
        recorder=recorder,
        instructions=instructions,
        greeting=build_greeting(kb, recorder.lead, direction),
        greet_on_enter=(direction != "outbound"),
    )
    session = build_session(kb, ctx.proc.userdata["vad"])

    # ---- silence handling: ask once, then end politely ----
    # Outbound calls only count silence after a person answered and was greeted.
    state = {"silences": 0, "heard_user": False, "live": direction != "outbound"}

    @session.on("user_input_transcribed")
    def _on_transcript(ev) -> None:
        if ev.is_final and ev.transcript.strip():
            state["heard_user"] = True
            state["silences"] = 0

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        if ev.new_state != "away" or not state["live"]:
            return
        state["silences"] += 1
        if state["silences"] == 1:
            session.generate_reply(instructions="The line has been silent. In one short sentence, gently ask if they can hear you.")
        else:
            recorder.end_call("call_dropped" if state["heard_user"] else "no_answer", "silence")
            hang_up_after(session.say(GOODBYE_KN), session)

    # ---- maximum call time ----
    async def call_timer() -> None:
        limit = rules.get("max_call_seconds", 300)
        await asyncio.sleep(max(limit - 45, 0))
        session.generate_reply(instructions=(
            "The call is near its time limit. In one sentence propose the free demo or a callback, "
            "then use the right tool to record it or end the call."))
        await asyncio.sleep(45)
        recorder.end_call("interested", "time limit reached")
        hang_up_after(session.say(GOODBYE_KN), session)

    # ---- end of call: write outcome and usage ----
    async def finish() -> None:
        if timer:
            timer.cancel()
        usage = summarize_usage(session.usage.model_usage)
        usage["call_seconds"] = (now_ist() - recorder.started_at).total_seconds()
        cost = recorder.finish(usage, load_pricing())
        logger.info(f"call {recorder.call_id} {recorder.outcome or 'call_dropped'} usage={usage} cost={cost}")
        db.close()
        if direction != "console":
            try:
                await ctx.delete_room()
            except Exception as e:  # room may already be gone
                logger.debug(f"delete_room: {e}")

    timer = None
    ctx.add_shutdown_callback(finish)
    session.on("close", lambda _: ctx.shutdown("session closed"))

    await session.start(agent=agent, room=ctx.room)
    if direction != "outbound":
        timer = asyncio.create_task(call_timer())
        return

    # ---- outbound (only after DLT): listen first, then dial, then check for voicemail ----
    if session.room_io:
        session.room_io.set_participant(phone)
    async with AMD(session, llm=session.llm, participant_identity=phone) as detector:
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=os.environ["SIP_OUTBOUND_TRUNK_ID"],
                    sip_call_to=phone,
                    participant_identity=phone,
                    wait_until_answered=True,
                ),
                timeout=45,
            )
        except (api.SipCallError, asyncio.TimeoutError) as e:
            logger.info(f"call not answered: {e}")
            recorder.end_call("no_answer")
            ctx.shutdown("not answered")
            return
        result = await detector.execute()
        if result.category.startswith("machine"):
            # Our rule: never pitch to a machine and leave no sales message.
            recorder.end_call("voicemail", result.category)
            ctx.shutdown("answering machine")
            return
    state["live"] = True
    agent.greet()
    timer = asyncio.create_task(call_timer())


if __name__ == "__main__":
    cli.run_app(server)
