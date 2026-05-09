# JusticeLine — Claude Code Instructions

## Project

AI-powered multilingual legal helpline. Callers phone a Twilio number, speak in their native language, get walked through a legal intake, and receive OpenJustice-powered legal guidance + SMS resources.

**Hackathon**: Montreal AI x Law Hackathon 2026 — Track #3 Conflict Analytics Lab
**Deadline**: 2026-05-09 19:00 hard cutoff

## Stack

- **Backend**: Python FastAPI on Google Cloud Run
- **Voice**: Twilio Media Streams (WebSocket) + Google Cloud STT (multilingual)
- **LLM**: Vertex AI (Gemini) for conversation orchestration and response generation
- **Legal reasoning**: OpenJustice API (`POST /dialog-flow-executions/run`)
- **SMS**: Twilio Messaging API
- **Deployment domain**: `openjustice-agent-966017992454.us-central1.run.app`

## Architecture

```
Caller → Twilio (phone) → POST /twilio-webhook → TwiML with Media Stream
                                                          ↓
                                         WebSocket /media (audio chunks)
                                                          ↓
                                           Google Cloud STT (multilingual)
                                                          ↓
                                           Session state lookup (CallSid)
                                                          ↓
                                        Gemini conversation orchestrator
                                                          ↓
                                      OpenJustice API (when facts ready)
                                                          ↓
                                    Twilio REST API (inject TTS response)
                                                          ↓
                                         Twilio SMS (follow-up resources)
```

## Key Files

- `main.py` — FastAPI app entry point
- `requirements.txt` — Python dependencies
- `.planning/` — GSD planning artifacts (do not edit manually)

## Env Vars

```
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
OPENJUSTICE_API_KEY=
OPENJUSTICE_DIALOG_FLOW_ID=
GOOGLE_CLOUD_PROJECT=
OPENJUSTICE_BASE_URL=https://api.openjustice.ai/api
```

## GSD Workflow

- Config: `.planning/config.json` (YOLO mode, coarse granularity, research + plan check + verify enabled)
- Roadmap: `.planning/ROADMAP.md`
- Current state: `.planning/STATE.md`
- Run phases with: `/gsd-plan-phase N` then `/gsd-execute-phase N`

## Critical Constraints

1. **No code commits after 7:00 PM** — hard hackathon rule
2. **OpenJustice dialog flow must be set up manually** in the OpenJustice web UI before Phase 3 — get the `dialogFlowId` UUID
3. **Session state is in-memory** — Cloud Run single instance only (fine for demo)
4. **Twilio Media Streams** requires the webhook to return TwiML with `<Connect><Stream>`, then uses the Twilio REST API to speak responses back mid-call
