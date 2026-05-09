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
                    "intake_stage": "situation",  # greeting fires immediately below
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
    """Play the 3-part scripted opening with pauses, matching idea.txt flow:
    1. Emergency disclaimer  →  5s pause
    2. AI disclaimer         →  5s pause
    3. Situation prompt      →  listen
    """
    import time
    time.sleep(0.8)  # let stream stabilize

    session = sessions.get(call_sid)
    if not session:
        return

    # Part 1 — emergency disclaimer
    emergency = (
        "Welcome to JusticeLine. / Bienvenue à JusticeLine. / مرحباً بك في JusticeLine. "
        "If this is an emergency, hang up and dial 9-1-1 immediately."
    )
    print(f"[main] Greeting part 1 for {call_sid}", flush=True)
    speak_response(call_sid, emergency, websocket, loop)
    time.sleep(5)

    if call_sid not in sessions:
        return

    # Part 2 — AI disclaimer
    ai_disclaimer = (
        "This is an AI-powered legal helpline. It is prone to error. "
        "Please stay on the line if you understand and accept this."
    )
    print(f"[main] Greeting part 2 for {call_sid}", flush=True)
    speak_response(call_sid, ai_disclaimer, websocket, loop)
    time.sleep(5)

    if call_sid not in sessions:
        return

    # Part 3 — situation prompt
    situation_prompt = "Please tell me about your legal situation."
    print(f"[main] Greeting part 3 for {call_sid}", flush=True)
    speak_response(call_sid, situation_prompt, websocket, loop)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
