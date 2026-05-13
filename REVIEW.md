# Code Review

> **Historical snapshot** — reflects code state at review time (pre-fix). Issues listed below were addressed in PR #3 (hotline-fixes-and-security). Statuses in this document are not updated.

**Reviewed:** 2026-05-12  
**Depth:** deep (cross-file analysis)  
**Files Reviewed:** config.py, llm.py, main.py, openjustice.py, sms.py, stt.py, tts.py, tests/__init__.py, tests/conftest.py, tests/test_session.py, tests/test_stt.py, tests/test_tts.py, tests/test_webhook.py

## Summary

- **Critical:** 7  
- **Warning:** 6  
- **Info:** 4  

The codebase has undergone an architectural shift from a 3-service pipeline (Google STT + LLM + Google TTS) to a unified Gemini Live API pipeline. The shift is partially complete: `main.py` is fully migrated to Gemini Live, but `stt.py`, `tts.py`, and `llm.py` were not deleted and are no longer wired into the application. Critically, `config.py` was never updated to export the symbols those legacy modules require, meaning any import of them causes an immediate `ImportError` — which also breaks the entire test suite. On top of this, the webhook endpoint has no Twilio signature validation, a service account private key file is present in the working directory and will be baked into the Docker image, and the OpenJustice API key is printed to stdout on every call.

---

## Critical Issues

### [CRITICAL-001] config.py missing five exported symbols — any import of stt.py, tts.py, or llm.py raises ImportError at startup

**File:** `config.py` (entire file)  
**Issue:** Multiple modules declare imports from `config` that do not exist there:
- `llm.py:15` — `from config import gemini_model, translate_client, sessions`
- `stt.py:3` — `from config import speech_client, translate_client, sessions`
- `tts.py:18` — `from config import tts_client, sessions`

`config.py` defines only `PROJECT_ID`, `LOCATION`, `DOMAIN`, `twilio_account_sid`, `twilio_auth_token`, and `twilio_client`. None of `gemini_model`, `translate_client`, `sessions`, `speech_client`, or `tts_client` exist anywhere in the codebase. Any process that imports these modules — including the entire `tests/` suite — will crash with `ImportError: cannot import name 'sessions' from 'config'`.  

**Impact:** The test suite is completely broken. If `stt.py`, `tts.py`, or `llm.py` are ever re-wired into the application, the service will fail to start.  

**Fix:** Either (a) delete the three dead modules and the tests that cover them, or (b) add the missing exports to `config.py`:
```python
# config.py additions
sessions: dict[str, dict] = {}

# Google Cloud clients (only instantiate if legacy pipeline is in use)
from google.cloud import speech, texttospeech_v1 as texttospeech, translate_v2 as translate
import google.generativeai as genai

speech_client = speech.SpeechClient()
tts_client = texttospeech.TextToSpeechClient()
translate_client = translate.Client()
gemini_model = genai.GenerativeModel("gemini-1.5-flash")
```
Option (a) is preferred given the architecture has moved to Gemini Live.

---

### [CRITICAL-002] No Twilio webhook signature validation — any unauthenticated HTTP POST triggers a Gemini Live session

**File:** `main.py:90-107`  
**Issue:** The `/twilio-webhook` endpoint accepts any POST request without verifying the `X-Twilio-Signature` header. Twilio provides a HMAC-SHA1 signature over the request URL + POST body using the auth token, and the official SDK ships `twilio.request_validator.RequestValidator` for this purpose. Without this check, any attacker who discovers the public URL can:
1. Flood the endpoint with fake calls, creating Gemini Live sessions and consuming GCP quota/billing.
2. Inject arbitrary `From` numbers to redirect SMS resources to any phone.
3. Probe the call flow and OJ API with crafted inputs.

```python
# main.py:90-107 — no validation at all
@app.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    from_number = form.get("From", "")
```

**Impact:** Unauthorized call initiation, GCP/Twilio billing abuse, SMS spoofing, API key exhaustion.  

**Fix:**
```python
from twilio.request_validator import RequestValidator

@app.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    validator = RequestValidator(twilio_auth_token)
    form = await request.form()
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    if not validator.validate(url, dict(form), signature):
        return Response(status_code=403, content="Forbidden")
    # ... rest of handler
```

---

### [CRITICAL-003] Service account private key committed to working directory and will be baked into Docker image

**File:** `hackathon-key.json` (root of repo), `Dockerfile:5`  
**Issue:** A GCP service account JSON key file (`hackathon-key.json`) containing a live RSA private key is present in the working directory. The `Dockerfile` runs `COPY . .` with no `.dockerignore`, so the key will be embedded in every built Docker image and pushed to any container registry. The `.gitignore` correctly excludes it from commits, but:
1. It is on disk and will enter every Docker image layer.
2. Any `docker push` exposes it to everyone with registry pull access.
3. The key is for project `openjustice-hackathon-2026`, account `966017992454-compute@developer.gserviceaccount.com`.

**Impact:** Full GCP account compromise if the image is ever pushed to a registry. Persistent threat because rotating the key does not remove it from existing images.  

**Fix:**
1. Rotate/revoke the exposed key immediately in the GCP IAM console.
2. Create `.dockerignore` at the repo root:
```
hackathon-key.json
.env
.venv
.git
.planning
```
3. Use Workload Identity Federation or inject credentials via Cloud Run's built-in service account rather than a key file.
4. Verify the key was never committed to git history: `git log --all --full-history -- hackathon-key.json`.

---

### [CRITICAL-004] OpenJustice API key logged to stdout on every call

**File:** `openjustice.py:18`  
**Issue:**
```python
print("Using key and flow:", OJ_KEY, OJ_FLOW_ID, flush=True)
```
`OJ_KEY` is the `OPENJUSTICE_API_KEY` bearer token. This line executes unconditionally at the top of `query_openjustice()`, which is called on every call that reaches the `waiting_oj` stage. In Cloud Run, stdout is shipped to Cloud Logging and is readable by any IAM principal with `logging.logEntries.list` — a broad permission often granted to developers. The key will also appear in any log export (BigQuery, GCS, Pub/Sub).  

**Impact:** API key exposure in structured logs; any team member or compromised logging pipeline can extract it.  

**Fix:**
```python
# Remove line 18 entirely.
# Retain the safe log line already present on line 24:
print(f"[oj] Querying dialog flow {OJ_FLOW_ID}: {message[:120]!r}", flush=True)
```

---

### [CRITICAL-005] Unprotected /media WebSocket endpoint — no authentication or origin check

**File:** `main.py:142-144`  
**Issue:**
```python
@app.websocket("/media")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
```
The WebSocket is accepted unconditionally from any origin. Twilio does not sign WebSocket connections. Any external client that connects to `wss://domain/media` will:
1. Receive a Gemini Live session opened against the production GCP project.
2. Be sent the initial greeting prompt (line 234-240), triggering a live Gemini session at cost.
3. Be able to stream arbitrary audio into the Gemini model.

**Impact:** GCP Gemini API quota/billing abuse; potential for prompt injection via audio; resource exhaustion.  

**Fix:** Validate the origin header or use a pre-shared token in the query parameter, as Twilio supports `<Stream url="wss://domain/media?token=XYZ" />`:
```python
@app.websocket("/media")
async def media_stream(websocket: WebSocket, token: str = ""):
    expected = os.getenv("WEBSOCKET_SECRET", "")
    if expected and token != expected:
        await websocket.close(code=4001)
        return
    await websocket.accept()
```
Then set the token in TwiML: `stream_url = f"wss://{DOMAIN}/media?token={WEBSOCKET_SECRET}"`.

---

### [CRITICAL-006] KeyError crash on malformed WebSocket messages — no defensive key access

**File:** `main.py:226-227, 243`  
**Issue:** WebSocket message fields are accessed with direct dict indexing, not `.get()`:
```python
call_sid = data["start"]["callSid"]      # line 226 — KeyError if missing
stream_sid = data["start"]["streamSid"]  # line 227 — KeyError if missing
chunk = base64.b64decode(data["media"]["payload"])  # line 243 — KeyError if missing
```
If Twilio sends a malformed or unexpected event (e.g. a `connected` event before `start`, or a `mark` event), the outer `except Exception` on line 254 will catch the crash and print a traceback — but the `finally` block will cancel `receiver_task` and close the session, dropping the live call.  

**Impact:** Any unexpected Twilio event type (e.g. `mark`, `dtmf`) silently terminates the call.  

**Fix:**
```python
if event == "start":
    start_data = data.get("start", {})
    call_sid = start_data.get("callSid", "")
    stream_sid = start_data.get("streamSid", "")
    if not call_sid or not stream_sid:
        print("[main] Malformed start event", flush=True)
        continue

elif event == "media":
    media_data = data.get("media", {})
    payload = media_data.get("payload")
    if not payload:
        continue
    chunk = base64.b64decode(payload)
```

---

### [CRITICAL-007] JSON parse error on non-JSON WebSocket message crashes the call

**File:** `main.py:222`  
**Issue:**
```python
async for message in websocket.iter_text():
    data = json.loads(message)  # line 222 — unguarded
```
`json.loads()` raises `json.JSONDecodeError` if the message is not valid JSON. Twilio Media Streams always sends JSON, but a network proxy, a test client, or a Twilio edge case (e.g. a keepalive ping forwarded as text) would cause an unhandled exception caught by the outer `except Exception` on line 254, which cancels `receiver_task` and terminates the call.  

**Impact:** Single malformed message kills the active call.  

**Fix:**
```python
try:
    data = json.loads(message)
except json.JSONDecodeError:
    print(f"[main] Non-JSON message ignored: {message[:80]!r}", flush=True)
    continue
```

---

## Warnings

### [WARNING-001] stt.py, tts.py, and llm.py are orphaned dead code — not imported by main.py

**File:** `stt.py`, `tts.py`, `llm.py`  
**Issue:** After the Gemini Live refactor, `main.py` no longer imports any of these three modules. The entire 3-service pipeline (Google STT → LLM stage machine → Google TTS) is unreachable from the running application. The test suite for these modules also depends on config symbols that don't exist (see CRITICAL-001), making the tests permanently broken until someone either removes the files or completes the config.  

**Impact:** Dead code that misleads contributors, inflates test count with non-running tests, and adds maintenance burden. `google-cloud-speech` and `google-cloud-texttospeech` are not even in `requirements.txt`, so the imports in these files will fail at the module level regardless of config.  

**Fix:** Delete `stt.py`, `tts.py`, `llm.py`, and the corresponding test files `test_stt.py`, `test_tts.py`. Keep `test_session.py` and `test_webhook.py` which test live code paths.

---

### [WARNING-002] _pending_callers dict leaks entries when WebSocket never receives "start" event

**File:** `main.py:82, 96, 228`  
**Issue:** `_pending_callers` is populated in the HTTP webhook handler (line 96) and consumed in the WebSocket handler on `"start"` event (line 228 with `.pop()`). If the WebSocket connection is established but the Twilio `"start"` event is never received (e.g. call dropped before stream handshake, Twilio error, connection timeout), the entry remains in the dict forever. Over many failed calls this is an unbounded memory leak.  

**Fix:**
```python
# In the websocket handler's finally block, add cleanup:
finally:
    receiver_task.cancel()
    try:
        await receiver_task
    except (asyncio.CancelledError, Exception):
        pass
    if call_sid:
        _pending_callers.pop(call_sid, None)  # clean up if "start" never fired
    print(f"[main] Session closed for {call_sid}", flush=True)
```

---

### [WARNING-003] session is never created in the sessions dict in the new Gemini Live architecture

**File:** `main.py:142-270`  
**Issue:** The new `media_stream` WebSocket handler never creates a `sessions[call_sid]` entry. However, `tts.py:speak_response` and `stt.py:_process_utterance` both read from `config.sessions[call_sid]`. While these modules are currently dead code, the missing session initialization is a correctness gap: if the legacy pipeline is ever re-enabled, `tts.py` will silently skip all audio output because `sessions.get(call_sid)` returns `None`.  

Also, the `test_session.py` tests check that `config.sessions` exists as a dict — but `config.py` does not define `sessions` at all (see CRITICAL-001), so these tests will fail with `AttributeError: module 'config' has no attribute 'sessions'`.  

**Fix:** Add `sessions: dict[str, dict] = {}` to `config.py`. If re-enabling the legacy pipeline, add session initialization on the `"start"` WebSocket event.

---

### [WARNING-004] followup_count limit is off-by-one — 6 follow-ups are allowed, not 5

**File:** `llm.py:104-105`  
**Issue:**
```python
session["followup_count"] = session.get("followup_count", 0) + 1  # increments first
if session.get("followup_count", 0) > 5:                          # then checks
```
The increment happens before the guard. On the 6th follow-up question, `followup_count` is set to 6 and the check `6 > 5` is True, triggering goodbye. This means 5 questions are answered and the 6th triggers the exit. The system prompt (main.py:47) says "Answer up to 5", and the `llm.py` docstring says "answering follow-up questions" — the intent is 5 answered questions. But the count reaches 6 before the exit fires, which is confusing and inconsistent with the stated limit.  

**Fix:**
```python
session["followup_count"] = session.get("followup_count", 0) + 1
if session["followup_count"] > 5:  # exits after 5 answers, not 6
    ...
```
Or restructure to check before incrementing:
```python
if session.get("followup_count", 0) >= 5:
    session["intake_stage"] = "done"
    return _translate("Thank you for calling JusticeLine. Take care, and goodbye.", language_code)
session["followup_count"] = session.get("followup_count", 0) + 1
```

---

### [WARNING-005] stt.py sends SMS with potentially None caller_number without validation

**File:** `stt.py:83-87`  
**Issue:**
```python
if session and session.pop("send_sms", False):
    caller_number = session.get("caller_number")   # can be None — key never set
    lang = session.get("language", "en-US")
    send_sms_resources(caller_number, lang)         # passes None to Twilio
```
The session dict is initialized (in the old pipeline) without a `caller_number` key. `session.get("caller_number")` returns `None`. `send_sms_resources` does check for a falsy `to_number` and returns `False`, but the `caller_number` is never populated anywhere in the old pipeline. In the new `main.py`, `caller_number` is a local variable in the WebSocket handler and is correctly passed to `_handle_tool_call`, but this code path in `stt.py` is dead.  

**Fix:** In the old pipeline, populate `caller_number` in the session on `"start"` event. In the new architecture, this is handled correctly in `_handle_tool_call`.

---

### [WARNING-006] speak_response blocks the STT worker thread for full audio playback duration

**File:** `tts.py:121-123`  
**Issue:**
```python
playback_seconds = len(mulaw_bytes) / 8000.0
import time; time.sleep(playback_seconds + 0.5)
```
`speak_response` is called from the STT recognition loop thread. The `time.sleep()` blocks that thread for the entire TTS audio duration plus 500ms. During this time the `run_recognition_loop` in `stt.py` cannot process any new speech events. While the intent is to prevent echo (hearing TTS output as user speech), the implementation means the STT thread is fully stalled. For a 10-second TTS response, the thread is dead for 10.5 seconds. Any user speech during that window is buffered in the `audio_queue` but the STT generator is not consuming it. The `import time` inside a hot loop is also a minor quality issue.  

**Fix:** Move the `import time` to the module level. For the blocking issue, consider using a threading.Event that gets cleared when the audio queue drains rather than a fixed sleep based on byte count (byte count does not account for network jitter or Twilio buffering).

---

## Info

### [INFO-001] audioop-lts Dockerfile/Python version mismatch

**File:** `Dockerfile:1`, `requirements.txt:10`  
**Issue:** The Dockerfile uses `python:3.11-slim`. `requirements.txt` pins `audioop-lts; python_version>="3.13"` (the `audioop` backport for Python 3.13+ where the stdlib module was removed). On Python 3.11, `audioop` is part of the stdlib and the conditional prevents `audioop-lts` from installing. `main.py:14-17` handles this correctly with a try/except import fallback. However, if the Docker base image is ever upgraded to Python 3.13, the `audioop_lts` import alias must match the package's actual module name.  

**Fix:** This is low risk as-is. Document the dependency: add a comment in `requirements.txt` noting that upgrading to Python 3.13 requires verifying the `audioop_lts` module name.

---

### [INFO-002] Magic default project ID and domain hardcoded in config.py

**File:** `config.py:9, 11`  
**Issue:**
```python
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "openjustice-hackathon-2026")
DOMAIN = _normalize_host(os.getenv("TWILIO_STREAM_HOST", "openjustice-agent-966017992454.us-central1.run.app"))
```
Both have hardcoded production values as defaults. If `GCP_PROJECT_ID` or `TWILIO_STREAM_HOST` environment variables are absent (e.g. in local dev without a `.env` file), the service will silently connect to the production GCP project and production Cloud Run URL.  

**Fix:** Default to empty string and fail fast with a clear error if not set:
```python
PROJECT_ID = os.getenv("GCP_PROJECT_ID") or (_ := None) or (_ for _ in ()).throw(EnvironmentError("GCP_PROJECT_ID is required"))
```
Or more readably, add a startup validation function that checks required env vars and exits with a clear message.

---

### [INFO-003] Debug-style inline imports scattered throughout hot paths

**File:** `stt.py:141`, `tts.py:123`  
**Issue:**
```python
import time; time.sleep(0.5)        # stt.py:141
import time; time.sleep(...)         # tts.py:123
```
`import time` is called inside loops and functions that execute on every utterance. Python caches imports in `sys.modules` so this is functionally correct, but it is a code smell that signals these were added hastily. The semicolon-separated statement style also obscures what's happening.  

**Fix:** Move `import time` to the top of each file.

---

### [INFO-004] test_webhook.py does not assert that unauthorized requests are rejected

**File:** `tests/test_webhook.py`  
**Issue:** The two webhook tests only check that a valid-looking POST returns 200 with correct TwiML. There is no test that sends a request without a `X-Twilio-Signature` header and asserts it gets rejected. Once CRITICAL-002 is fixed, this test gap means regression protection for the auth check is absent.  

**Fix:** Add a test:
```python
def test_webhook_rejects_unsigned_request():
    client = TestClient(app)
    response = client.post("/twilio-webhook", data={"CallSid": "CA123", "From": "+15551234567"})
    assert response.status_code == 403
```

---

_Reviewed: 2026-05-12_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: deep_
