# Roadmap — JusticeLine

**4 phases** | **13 requirements** | Hackathon deadline: 2026-05-09 19:00

---

### Phase 1: Call Infrastructure
**Goal:** Establish end-to-end call skeleton — Twilio calls in, WebSocket streams audio, Google Cloud STT transcribes, system speaks back via Twilio REST API, session state works
**Mode:** mvp
**Requirements:** VOICE-01, VOICE-02, VOICE-03, VOICE-04
**Success Criteria:**
1. A real phone call to the Twilio number reaches the FastAPI webhook
2. Caller speech is transcribed with language detected correctly
3. System speaks a response back to the caller mid-stream using Twilio REST API
4. Second call has clean session state (no bleed from previous)

**Estimated time:** 45 min
**Status:** not started

---

### Phase 2: Multilingual Intake Flow
**Goal:** Full scripted intake — language detection, disclaimers, situation + jurisdiction collection, Gemini-driven clarifying questions
**Mode:** mvp
**Requirements:** INTAKE-01, INTAKE-02, INTAKE-03, INTAKE-04, INTAKE-05, INTAKE-06
**Success Criteria:**
1. Caller speaking French is responded to in French throughout the call
2. Emergency and AI disclaimers are played in the detected language with pauses
3. System extracts situation and jurisdiction from conversation
4. Gemini asks at least one clarifying question when facts are insufficient
5. System signals "ready for OpenJustice" when jurisdiction + situation are present

**Estimated time:** 60 min
**Status:** not started

---

### Phase 3: OpenJustice Legal Reasoning
**Goal:** Query OpenJustice API with collected facts, receive reasoning, explain result to caller in their language, handle follow-up Q&A
**Mode:** mvp
**Requirements:** LEGAL-01, LEGAL-02, LEGAL-03, LEGAL-04
**Success Criteria:**
1. OpenJustice dialog flow exists and returns legal reasoning for a sample case
2. Caller hears "please wait" while OpenJustice processes
3. Legal result is summarized and explained in plain language in the caller's language
4. Caller can ask a follow-up question and receive a relevant answer

**Estimated time:** 45 min
**Status:** not started

---

### Phase 4: SMS Follow-up + Demo Polish
**Goal:** SMS delivery of legal resources, clean call ending, end-to-end demo run
**Mode:** mvp
**Requirements:** SMS-01, SMS-02, SMS-03
**Success Criteria:**
1. Caller receives SMS with clinic number or resource link within 30s of requesting it
2. Call ends with language-appropriate goodbye
3. Full demo call (FR or EN) completes without errors end-to-end
4. Error in one phase (e.g., OpenJustice timeout) degrades gracefully without crashing

**Estimated time:** 30 min
**Status:** not started

---

## Build Order

```
Phase 1 (infra) → Phase 2 (intake) → Phase 3 (legal) → Phase 4 (SMS + polish)
```

Each phase is sequential — each builds on the previous.
