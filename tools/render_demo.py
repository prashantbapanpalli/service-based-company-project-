"""Render data/demo_call.json to one audio file so you can hear how a call should sound.

    python tools/render_demo.py                    # Sarvam bulbul:v3 voices (needs SARVAM_API_KEY)
    python tools/render_demo.py --engine espeak    # offline, robotic voice (needs espeak-ng installed)
    python tools/render_demo.py --agent-voice kavya --customer-voice rahul --out demo.wav

The conversation is a scripted example of the intended behaviour, not a
recording of the real AI. Use `python agent.py console` to hear the real agent.
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO = ROOT / "data" / "demo_call.json"
RATE = 22050
GAP_SECONDS = 0.6


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


async def sarvam_pcm(text, speaker, session):
    """16-bit mono PCM at RATE using the same LiveKit Sarvam plugin as agent.py."""
    from livekit.plugins import sarvam

    tts = sarvam.TTS(target_language_code="kn-IN", model="bulbul:v3", speaker=speaker,
                     speech_sample_rate=RATE, http_session=session)
    chunks = []
    async for ev in tts.synthesize(text):
        chunks.append(bytes(ev.frame.data))
    return b"".join(chunks)


def espeak_pcm(text, speaker):
    """16-bit mono PCM at RATE from espeak-ng (offline, robotic)."""
    voice, pitch = ("kn+f3", "55") if speaker == "agent" else ("kn", "30")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        subprocess.run(["espeak-ng", "-v", voice, "-p", pitch, "-s", "140", "-w", str(raw), text], check=True)
        with wave.open(str(raw)) as w:
            frames, rate = w.readframes(w.getnframes()), w.getframerate()
    if rate == RATE:
        return frames
    # espeak-ng writes 22050 Hz by default; resample with ffmpeg if it ever differs.
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1", "-i", "-",
                          "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-"], input=frames, capture_output=True, check=True)
    return out.stdout


async def render(engine, agent_voice, customer_voice, out_path):
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    silence = b"\x00\x00" * int(RATE * GAP_SECONDS)
    parts = []
    session = None
    if engine == "sarvam":
        import aiohttp
        session = aiohttp.ClientSession()
    try:
        for i, turn in enumerate(demo["turns"], 1):
            print(f"{i:2}. {turn['speaker']:8} {turn['en']}")
            if engine == "sarvam":
                voice = agent_voice if turn["speaker"] == "agent" else customer_voice
                parts.append(await sarvam_pcm(turn["kn"], voice, session))
            else:
                parts.append(espeak_pcm(turn["kn"], turn["speaker"]))
            parts.append(silence)
    finally:
        if session:
            await session.close()
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(parts))
    seconds = sum(len(p) for p in parts) / 2 / RATE
    print(f"\nWrote {out_path} ({seconds:.0f} seconds, {engine} voices)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", choices=["sarvam", "espeak"], default=None)
    parser.add_argument("--agent-voice", default="kavya", help="bulbul:v3 speaker for the agent")
    parser.add_argument("--customer-voice", default="rahul", help="bulbul:v3 speaker for the customer")
    parser.add_argument("--out", default=str(ROOT / "demo_call.wav"))
    args = parser.parse_args(argv)
    load_env()
    engine = args.engine or ("sarvam" if os.environ.get("SARVAM_API_KEY") else "espeak")
    if engine == "espeak" and not shutil.which("espeak-ng"):
        print("espeak-ng is not installed. Set SARVAM_API_KEY in .env to use Sarvam voices instead.")
        return 1
    asyncio.run(render(engine, args.agent_voice, args.customer_voice, Path(args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
