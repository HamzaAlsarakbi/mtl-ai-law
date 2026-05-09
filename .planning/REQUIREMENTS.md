# Requirements — JusticeLine

## v1 Requirements

### Voice Infrastructure
- [ ] **VOICE-01**: Twilio phone call triggers the FastAPI webhook endpoint
- [ ] **VOICE-02**: Google Cloud STT transcribes spoken audio with automatic language detection (en, fr, ar, es, pt, zh, hi supported)
- [ ] **VOICE-03**: System responds to caller using language-appropriate Twilio TTS voice
- [ ] **VOICE-04**: Session state persisted per CallSid for the duration of the call

### Call Flow — Intake
- [ ] **INTAKE-01**: System detects caller's language from first utterance and responds in that language
- [ ] **INTAKE-02**: Emergency disclaimer played ("If this is an emergency, hang up and dial 911") + 5s pause
- [ ] **INTAKE-03**: AI disclaimer played ("This is an AI-powered legal helpline, it is prone to error...") + 5s pause
- [ ] **INTAKE-04**: System asks caller to describe their situation and waits for 2s silence
- [ ] **INTAKE-05**: System asks caller for their location/jurisdiction and waits for 2s silence
- [ ] **INTAKE-06**: Gemini asks up to 3 clarifying questions until jurisdiction + situation are sufficient for OpenJustice

### Legal Reasoning
- [ ] **LEGAL-01**: System calls OpenJustice `/dialog-flow-executions/run` with collected facts (jurisdiction, situation, profile)
- [ ] **LEGAL-02**: Caller is told to wait while OpenJustice processes
- [ ] **LEGAL-03**: OpenJustice result (reasoning + recommendations) explained to caller in their language via Gemini
- [ ] **LEGAL-04**: Caller can ask up to 5 follow-up questions about the result

### SMS Follow-up
- [ ] **SMS-01**: System offers caller choice: legal documentation and/or legal clinic referral via SMS
- [ ] **SMS-02**: Twilio sends SMS to caller's number with requested resources (clinic number and/or resource link)
- [ ] **SMS-03**: System confirms SMS was sent and ends call with language-appropriate goodbye

## v2 Requirements (deferred — post-hackathon)

- Persistent call history / database storage
- PDF generation for legal documents
- More jurisdictions beyond Canada
- Web dashboard for call logs
- Human escalation / warm transfer to legal clinic

## Out of Scope

- Web or mobile UI — voice-only for this demo
- Authentication or caller identity verification
- Real legal advice (disclaimer: AI guidance only)
- Production SLA / error recovery
- Database persistence

## Traceability

| REQ-ID | Phase |
|--------|-------|
| VOICE-01 through VOICE-04 | Phase 1 |
| INTAKE-01 through INTAKE-06 | Phase 2 |
| LEGAL-01 through LEGAL-04 | Phase 3 |
| SMS-01 through SMS-03 | Phase 4 |
