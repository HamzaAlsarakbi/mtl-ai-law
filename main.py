import json
import base64
import os
from fastapi import FastAPI, WebSocket, Response
from google.cloud import speech, translate_v2 as translate
from google.cloud import aiplatform

app = FastAPI()

# Initialize Google Cloud Clients
speech_client = speech.SpeechClient()
translate_client = translate.Client()

# Replace with your actual Cloud Run URL (without https://)
DOMAIN = "openjustice-agent-966017992454.us-central1.run.app"

@app.post("/twilio-webhook")
async def twilio_webhook():
    """Initial entry point for Twilio calls."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>Please describe your legal situation.</Say>
        <Connect>
            <Stream url="wss://{DOMAIN}/media" />
        </Connect>
        <Pause length="600" />
    </Response>
    """
    return Response(content=twiml, media_type="application/xml")

import queue
import threading

@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection established", flush=True)
    
    # Bridge between Async WebSocket and Sync Speech Client
    audio_queue = queue.Queue()

    # 1. Thread-safe generator for the Speech Client
    def request_generator():
        # The first request must contain the configuration
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            language_code="en-US",
            alternative_language_codes=["fr-CA", "ar-SA", "es-ES"],
        )
        streaming_config = speech.StreamingRecognitionConfig(config=config)
        yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)

        while True:
            chunk = audio_queue.get()
            if chunk is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    # 2. Function to process responses in a separate thread
    def process_responses():
        responses = speech_client.streaming_recognize(
            requests=request_generator(),
            config=None # Already sent in generator
        )
        try:
            for response in responses:
                for result in response.results:
                    if result.is_final:
                        user_text = result.alternatives[0].transcript
                        print(f"Detected: {user_text}", flush=True)
                        # Your translation/OpenJustice logic here
        except Exception as e:
            print(f"Speech Loop Error: {e}", flush=True)

    # Start the speech processing thread
    threading.Thread(target=process_responses, daemon=True).start()

    # 3. Main async loop to receive Twilio messages
    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            
            if data['event'] == 'media':
                audio_queue.put(base64.b64decode(data['media']['payload']))
            
            if data['event'] == 'stop':
                print("Twilio Stream Stopped", flush=True)
                break
    except Exception as e:
        print(f"WebSocket Loop Error: {e}", flush=True)
    finally:
        audio_queue.put(None) # Signal the generator to stop

if __name__ == "__main__":
    import uvicorn
    # Use port 8080 for Cloud Run compatibility
    uvicorn.run(app, host="0.0.0.0", port=8080)