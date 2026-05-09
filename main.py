import asyncio
import base64
import json
import queue
import threading

from fastapi import FastAPI, WebSocket, Response

from config import DOMAIN, sessions
from stt import run_recognition_loop

print("[main] Starting JusticeLine API", flush=True)
app = FastAPI()


@app.post("/twilio-webhook")
async def twilio_webhook():
    """Initial entry point for Twilio calls.

    Returns TwiML using <Connect><Stream> for bidirectional audio
    (RESEARCH Pattern 3 — <Start><Stream> would be one-way only).
    The <Pause length="600"> after <Connect> keeps the call alive
    for up to 10 minutes; the WebSocket handler drives actual flow.
    """
    stream_url = f"wss://{DOMAIN}/media"
    print(f"[main] Twilio webhook hit, streaming to {stream_url}", flush=True)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
    <Pause length="600" />
</Response>
"""
    return Response(content=twiml, media_type="text/xml")


@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    """Handles the bidirectional Twilio Media Stream.

    Captures the asyncio event loop reference so the STT worker thread
    can dispatch audio sends back via asyncio.run_coroutine_threadsafe
    (RESEARCH Pattern 2 / critical deviation #3). Captures streamSid
    from the 'start' event for outbound media routing (RESEARCH
    critical deviation #4). Initializes per-call session state
    (D-01) and cleans it up on 'stop' (or in `finally`) to prevent
    cross-call bleed and memory leaks.
    """
    print(f"[main] WebSocket handshake from {websocket.client}", flush=True)
    await websocket.accept()
    loop = asyncio.get_running_loop()
    print("[main] WebSocket connection established", flush=True)

    audio_queue: queue.Queue = queue.Queue()
    call_sid_ref: list = [None]  # mutable so STT thread sees value once 'start' arrives

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
                sessions[call_sid] = {
                    "language": "en-US",
                    "conversation_history": [],
                    "intake_stage": "greeting",
                    "stream_sid": stream_sid,
                    "is_speaking": False,
                }
                print(f"[main] start: callSid={call_sid} streamSid={stream_sid}", flush=True)
            elif event_type == "media":
                payload = base64.b64decode(data["media"]["payload"])
                audio_queue.put(payload)
            elif event_type == "stop":
                print("[main] Twilio stop event received", flush=True)
                break
    except Exception as e:
        print(f"[main] WebSocket loop error: {e}", flush=True)
    finally:
        # Clean up session regardless of how we exit (stop event, error, disconnect).
        # Without this, sessions dict grows unbounded across calls.
        call_sid = call_sid_ref[0]
        if call_sid and call_sid in sessions:
            del sessions[call_sid]
            print(f"[main] Session cleaned up for {call_sid}", flush=True)
        print("[main] WebSocket closing, signaling speech thread", flush=True)
        audio_queue.put(None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
