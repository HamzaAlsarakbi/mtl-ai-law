# JusticeLine — AI-Powered Multilingual Legal Helpline

## What This Is

A voice-based AI legal helpline that answers phone calls, detects the caller's language, walks them through an intake process, queries the OpenJustice legal reasoning API, and follows up with SMS resources. Built for the Montreal AI x Law Hackathon 2026, Challenge Track #3 — Conflict Analytics Lab.

## Core Value

A person in any language can call a single phone number and receive actionable legal guidance with relevant resources — no lawyer required, no language barrier.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Twilio phone call triggers the helpline flow
- [ ] Google Cloud STT transcribes caller speech with multilingual detection
- [ ] System detects and responds in caller's native language
- [ ] Emergency disclaimer (dial 911) played at call start with pause
- [ ] AI disclaimer played with pause
- [ ] System collects situation and jurisdiction from caller
- [ ] Clarifying questions asked via Gemini until sufficient facts gathered
- [ ] OpenJustice API called with jurisdiction + situation + profile
- [ ] OpenJustice result explained to caller in their language
- [ ] Caller can ask follow-up questions
- [ ] System offers legal docs and/or legal clinic number via SMS
- [ ] Twilio SMS delivers requested resources to caller
- [ ] Call ends with language-appropriate goodbye

### Out of Scope

- Web/app UI — voice-only for demo
- Persistent call history / database — in-memory session state only
- PDF generation — link to existing legal resources instead
- Production-grade error recovery — demo reliability only

## Context

- **Hackathon**: Montreal AI x Law Hackathon 2026, 10h window, Track #3 Conflict Analytics Lab (Conflict Analytics Lab / Queen's University)
- **Judging criteria**: Innovation & Creativity, Technical Execution, AI Utilization, Presentation & Pitch (5 pts each)
- **Deadline**: 7:00 PM hard cutoff, code commits after that = disqualification
- **Existing code**: FastAPI skeleton with Twilio Media Streams WebSocket + Google Cloud STT already scaffolded
- **Deployed domain**: `openjustice-agent-966017992454.us-central1.run.app`
- **OpenJustice**: API key available, dialog flow NOT yet configured — needs to be set up

## Constraints

- **Timeline**: ~3 hours remaining in hackathon as of project init
- **Stack**: Python FastAPI on Google Cloud Run (credits provided)
- **Voice**: Twilio (phone number provisioned) + Media Streams + Google Cloud STT
- **LLM**: Vertex AI (Gemini) via Google Cloud
- **Legal API**: OpenJustice (`POST /dialog-flow-executions/run`) — needs dialogFlowId
- **SMS**: Twilio Messaging API
- **No research time**: Build directly from known stack

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Twilio Media Streams over Gather | Real-time audio, better multilingual support, already in codebase | — Pending |
| Vertex AI Gemini for conversation | GCP credits provided, avoids external API cost, tight integration | — Pending |
| In-memory session state (CallSid key) | No time for Redis/DB in hackathon, single-server Cloud Run instance | — Pending |
| OpenJustice stateless `/run` endpoint | Simpler than session-based execution, sufficient for demo | — Pending |
| Twilio REST API to inject TTS mid-stream | Required to speak back while Media Stream is active | — Pending |

---
*Last updated: 2026-05-09 after initialization*

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted
