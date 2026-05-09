import base64
import json
import queue
import threading

from fastapi import FastAPI, WebSocket, Response

from config import DOMAIN
from stt import run_recognition_loop

print("[main] Starting JusticeLine API", flush=True)
app = FastAPI()


@app.post("/twilio-webhook")
async def twilio_webhook():
    """Initial entry point for Twilio calls."""
    stream_url = f"wss://{DOMAIN}/media"
    print(f"[main] Twilio webhook hit, streaming to {stream_url}", flush=True)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>What up.</Say>
        <Connect>
            <Stream url="{stream_url}" />
        </Connect>
        <Pause length="600" />
    </Response>
    """
    return Response(content=twiml, media_type="text/xml")


@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    print(f"[main] WebSocket handshake from {websocket.client}", flush=True)
    await websocket.accept()
    print("[main] WebSocket connection established", flush=True)

    audio_queue: queue.Queue = queue.Queue()
    call_sid_ref: list = [None]  # mutable so STT thread sees it once 'start' event arrives

    threading.Thread(
        target=run_recognition_loop,
        args=(audio_queue, call_sid_ref),
        daemon=True,
    ).start()

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event_type = data.get("event")

            if event_type == "start":
                call_sid_ref[0] = data.get("start", {}).get("callSid")
                print(f"[main] Call started: {call_sid_ref[0]}", flush=True)
            elif event_type == "media":
                payload = base64.b64decode(data["media"]["payload"])
                audio_queue.put(payload)
            elif event_type == "stop":
                print("[main] Twilio stop event received", flush=True)
                break
    except Exception as e:
        print(f"[main] WebSocket loop error: {e}", flush=True)
    finally:
        print("[main] WebSocket closing, signaling speech thread", flush=True)
        audio_queue.put(None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
