# GitHub research: repos that can improve the agent

Searched October 2026. Repos marked **read** were cloned and their code was checked; the
others come from search results only, so check their code, licence and activity before
using them.

## Use now (Phase 1–2)

| Repo | Licence | What it gives us | Status |
|---|---|---|---|
| [livekit/agents](https://github.com/livekit/agents) (v1.8.8) **read** | Apache-2.0 | The framework we use. Its Sarvam plugin has `STTRealtime(language="kn-IN", mode="codemix", prompt=...)`, so Kannada mixed with English is transcribed, and a vocabulary hint helps with names. `TTS(model="bulbul:v3", target_language_code="kn-IN", pace=..., dict_id=...)`; `dict_id` is a custom pronunciation dictionary for words like "SourceCode Studio". For phones: `encoding="mulaw"`, `sample_rate=8000`. | **Adopted:** `build_stt_prompt()` in `app/knowledge.py` builds the `prompt=` text from `stt_vocabulary` in the knowledge base. |
| livekit/agents → `examples/data_capture_sim` **read** | Apache-2.0 | `lk agent simulate text agent.py --scenarios file.yaml`: an LLM plays the caller (persona plus opening line) and judges the agent against `agent_expectations`. | **Adopted:** `tools/export_simulations.py` writes `data/simulations.yaml` (26 scenarios) from our situations and objections. It runs once `agent.py` exists. |
| livekit/agents → `examples/survey/test_survey_agent.py` **read** | Apache-2.0 | pytest tests for an agent: `session.run(user_input=...)`, `contains_function_call()`, `judge(llm, intent=...)`, `mock_tools`. | **Next:** when `agent.py` exists, turn `tools/scenario_eval.py` into these tests so the real agent and its tools are tested, not only the prompt. |
| [livekit-examples/outbound-caller-python](https://github.com/livekit-examples/outbound-caller-python) **read** | MIT | A complete outbound agent: dialling with `create_sip_participant(wait_until_answered=True)`, plus `end_call` (waits for speech to finish, then deletes the room), `transfer_call` (SIP transfer to a person) and `detected_answering_machine` tools. | **Next:** template for our `agent.py`. Our 6 tools map onto these patterns. |
| livekit/agents → `examples/telephony/amd.py` **read** | Apache-2.0 | Built-in answering-machine detection (`AMD(session)`) with results `human`, `machine-vm`, `machine-ivr`, `machine-unavailable`, `uncertain`. | **Phase 2:** handles our `voicemail` situation before the LLM speaks. Our rule is to leave no sales message. |

## Later

| Repo | Licence | What it gives us | When |
|---|---|---|---|
| livekit/agents → `examples/warm-transfer` + `beta.workflows.WarmTransferTask` **read** | Apache-2.0 | Puts the caller on hold, calls Chetan, briefs him with a summary, then connects them. | Phase 3 (human handover). Upgrades `request_handover` from "callback later" to a live transfer. |
| [filip-michalsky/SalesGPT](https://github.com/filip-michalsky/SalesGPT) **read** | MIT | A sales agent with 8 conversation stages and a stage analyser. | **Adopted:** its "qualification" stage (confirm you're talking to the decision-maker) is now a field technique in the playbook. |
| [AI4Bharat/IndicConformerASR](https://github.com/AI4Bharat/IndicConformerASR) | MIT (per AIKosh listing) | Open-source Kannada speech recognition. | Only if Sarvam's cost or quality is a problem. Needs a GPU server. |
| AI4Bharat IndicF5 / Indic Parler-TTS | MIT (per AIKosh listing) | Open-source Kannada text-to-speech. | Same as above. |
| [ServiceNow EVA](https://huggingface.co/datasets/ServiceNow-AI/eva) | not checked | Research framework that scores full spoken conversations. | If we need audio-level benchmarks beyond `lk agent simulate`. |
| voicetest, egma, simulate-sdk | not checked | Small simulated-caller test harnesses. | Probably not needed; LiveKit's own simulator covers this. |

## Checked and not used

- **ProfitPilot, gtm-skills, cold-calling topic repos:** script generators or tied to paid
  dialers (Vapi/Twilio/n8n). They add nothing our playbook doesn't already cover.
- Code from these repos was **not copied** into this project; we only reuse documented
  API patterns. Respect each licence if code is copied later.
