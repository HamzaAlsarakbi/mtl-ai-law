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
# DOMAIN = "openjustice-agent-966017992454.us-central1.run.app"
DOMAIN = "https://shiftless-chosen-epilogue.ngrok-free.dev"

@app.post("/twilio-webhook")
async def twilio_webhook():
    """Initial entry point for Twilio calls."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>What up.</Say>
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
    
    audio_queue = queue.Queue()

    def request_generator():
        # Yield only raw audio bytes. 
        # The speech_client.streaming_recognize helper handles the config packet.
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def process_responses():
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            language_code="en-US",
            alternative_language_codes=["fr-CA", "ar-SA", "es-ES"],
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            enable_voice_activity_events=True,
            voice_activity_timeout=speech.StreamingRecognitionConfig.VoiceActivityTimeout(
                speech_end_timeout={"seconds": 2}
            )
        )

        try:
            # We pass the config here, and the generator only yields audio_content
            responses = speech_client.streaming_recognize(
                config=streaming_config,
                requests=request_generator(),
            )
            
            for response in responses:
                if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE:
                    print("--- 2 second pause detected ---", flush=True)
                    continue

                for result in response.results:
                    if result.is_final:
                        user_text = result.alternatives[0].transcript
                        print(f"Detected: {user_text}", flush=True)
                        
                        # Translation and OpenJustice logic
                        translated = translate_client.translate(user_text, target_language='en')
                        print(f"English: {translated['translatedText']}", flush=True)
                        
        except Exception as e:
            print(f"Speech Loop Error: {e}", flush=True)

    threading.Thread(target=process_responses, daemon=True).start()

    try:
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            if data['event'] == 'media':
                audio_queue.put(base64.b64decode(data['media']['payload']))
            if data['event'] == 'stop':
                break
    except Exception as e:
        print(f"WebSocket Loop Error: {e}", flush=True)
    finally:
        audio_queue.put(None)

if __name__ == "__main__":
    import uvicorn
    # Use port 8080 for Cloud Run compatibility
    uvicorn.run(app, host="0.0.0.0", port=8080)