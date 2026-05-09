import asyncio
import base64
import json
import queue
import threading

from fastapi import FastAPI, WebSocket, Request, Response

from config import DOMAIN, sessions
from stt import run_recognition_loop
from tts import speak_response

print("[main] Starting JusticeLine API", flush=True)
app = FastAPI()

# Temporary store: callSid → caller phone number, populated by /twilio-webhook
# before the WebSocket start event arrives.
_pending_caller_numbers: dict[str, str] = {}


@app.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    """Initial entry point for Twilio calls.

    Captures From number here because the WebSocket 'start' event
    doesn't include it. Returns TwiML with <Connect><Stream> for
    bidirectional audio (NOT <Start><Stream> which is one-way).
    The <Pause length="600"> keeps the call alive for up to 10 min.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    from_number = form_data.get("From", "")
    if call_sid:
        _pending_caller_numbers[call_sid] = from_number
        print(f"[main] Incoming call: CallSid={call_sid} From={from_number}", flush=True)

    stream_url = f"wss://{DOMAIN}/media"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
    <Pause length="600" />
</Response>
"""
    return Response(content=twiml, media_type="text/xml")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "JusticeLine"}


@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    """Bidirectional Twilio Media Stream handler.

    Captures the asyncio event loop so the STT worker thread can dispatch
    audio sends back via asyncio.run_coroutine_threadsafe. Plays the
    trilingual greeting immediately on connect (before the caller speaks).
    """
    print(f"[main] WebSocket handshake from {websocket.client}", flush=True)
    await websocket.accept()
    loop = asyncio.get_running_loop()
    print("[main] WebSocket connection established", flush=True)

    audio_queue: queue.Queue = queue.Queue()
    call_sid_ref: list = [None]  # mutable so STT thread sees callSid once 'start' arrives

    threading.Thread(
        target=run_recognition_loop,
        args=(audio_queue, call_sid_ref, websocket, loop),
        daemon=True,
    ).start()

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "start":
                start = data.get("start", {})
                call_sid = start.get("callSid")
                stream_sid = start.get("streamSid")
                call_sid_ref[0] = call_sid

                caller_number = _pending_caller_numbers.pop(call_sid, None)
                sessions[call_sid] = {
                    "language": "en-US",
                    "conversation_history": [],
                    "intake_stage": "greeting",  # blocks STT until greeting finishes
                    "stream_sid": stream_sid,
                    "is_speaking": False,
                    "situation_raw": None,
                    "jurisdiction": None,
                    "oj_result": None,
                    "followup_count": 0,
                    "caller_number": caller_number,
                    "send_sms": False,
                }
                print(f"[main] start: callSid={call_sid} streamSid={stream_sid} from={caller_number}", flush=True)

                # Play trilingual greeting without blocking the WebSocket receive loop
                threading.Thread(
                    target=_play_greeting,
                    args=(call_sid, websocket, loop),
                    daemon=True,
                ).start()

            elif event_type == "media":
                payload = base64.b64decode(data["media"]["payload"])
                audio_queue.put(payload)

            elif event_type == "stop":
                print("[main] Twilio stop event received", flush=True)
                break

    except Exception as e:
        print(f"[main] WebSocket loop error: {e}", flush=True)
    finally:
        call_sid = call_sid_ref[0]
        if call_sid and call_sid in sessions:
            del sessions[call_sid]
            print(f"[main] Session cleaned up for {call_sid}", flush=True)
        print("[main] WebSocket closing, signaling speech thread", flush=True)
        audio_queue.put(None)


def _play_greeting(call_sid: str, websocket, loop) -> None:
    """Play the 3-part scripted opening.

    Stage is "greeting" during this entire sequence — the STT thread discards
    any speech it picks up until we set the stage to "situation" at the end.

    1. Emergency disclaimer  →  2s pause
    2. AI disclaimer         →  2s pause
    3. Situation prompt      →  stage → "situation", STT now active
    """
    import time
    time.sleep(0.8)  # let Twilio stream stabilize

    session = sessions.get(call_sid)
    if not session:
        return

    # Part 1 — emergency disclaimer (English — clear, no garbled multilingual TTS)
    speak_response(
        call_sid,
        "Welcome to JusticeLine. "
        "If this is an emergency, please hang up and dial 9-1-1. "
        "You can speak to me in any language — English, French, Arabic, Spanish, or others.",
        websocket,
        loop,
    )
    time.sleep(2)

    if call_sid not in sessions:
        return

    # Part 2 — AI disclaimer
    speak_response(
        call_sid,
        "This is an AI-powered legal helpline. I am not a lawyer. "
        "Information I provide is general only and may contain errors. "
        "Please stay on the line if you understand.",
        websocket,
        loop,
    )
    time.sleep(2)

    if call_sid not in sessions:
        return

    # Part 3 — open situation prompt, then unlock STT
    speak_response(
        call_sid,
        "Please tell me about your legal situation.",
        websocket,
        loop,
    )

    # Greeting complete — allow STT to process caller speech
    session = sessions.get(call_sid)
    if session:
        session["intake_stage"] = "situation"
        print(f"[main] Greeting done for {call_sid}, STT now active", flush=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
