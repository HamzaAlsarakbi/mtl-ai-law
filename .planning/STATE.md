# Project State — JusticeLine

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-09)

**Core value:** A person in any language can call a single phone number and receive actionable legal guidance — no lawyer required, no language barrier.
**Current focus:** Phase 1 — Call Infrastructure

## Current Phase

**Phase 1: Call Infrastructure**
Goal: End-to-end call skeleton with Twilio Media Streams, Google Cloud STT, and Twilio REST API TTS

## Phase Status

| Phase | Name | Status |
|-------|------|--------|
| 1 | Call Infrastructure | not started |
| 2 | Multilingual Intake Flow | not started |
| 3 | OpenJustice Legal Reasoning | not started |
| 4 | SMS Follow-up + Demo Polish | not started |

## Key Env Vars Needed

```
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
OPENJUSTICE_API_KEY=
OPENJUSTICE_DIALOG_FLOW_ID=
GOOGLE_CLOUD_PROJECT=
```

## Critical Path Items

1. OpenJustice dialog flow must be created in the OpenJustice UI (no flow ID yet)
2. Cloud Run domain confirmed: `openjustice-agent-966017992454.us-central1.run.app`
3. Twilio webhook must point to `https://{DOMAIN}/twilio-webhook`
4. Google Cloud APIs to enable: Speech-to-Text, Translate, Vertex AI
