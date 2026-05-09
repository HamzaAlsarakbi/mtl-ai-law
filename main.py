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

@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("WebSocket connection established")
    
    # Configure Speech-to-Text with Auto-Language Detection
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
        sample_rate_hertz=8000,
        language_code="en-US",  # Primary
        alternative_language_codes=["fr-CA", "ar-SA", "es-ES"], # Detection list
    )

    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=False
    )

    async def request_generator():
        while True:
            try:
                message = await websocket.receive_text()
                data = json.loads(message)
                
                if data['event'] == 'start':
                    print(f"Twilio Stream Started: {data['start']['streamSid']}")
                    continue
                    
                if data['event'] == 'media':
                    # Extract raw audio bytes
                    payload = data['media']['payload']
                    yield speech.StreamingRecognizeRequest(audio_content=base64.b64decode(payload))
                
                if data['event'] == 'stop':
                    print("Twilio Stream Stopped")
                    break
            except Exception as e:
                print(f"Error in request_generator: {e}")
                break

    # Process the stream
    responses = speech_client.streaming_recognize(streaming_config, request_generator())

    try:
        for response in responses:
            for result in response.results:
                if result.is_final:
                    user_text = result.alternatives[0].transcript
                    detected_lang = result.language_code
                    
                    # 1. Translate detected language to English
                    translated = translate_client.translate(user_text, target_language='en')
                    english_text = translated['translatedText']
                    
                    print(f"[{detected_lang}] User: {user_text}")
                    print(f"[EN] Translated: {english_text}")

                    # 2. Logic for OpenJustice/Gemini query goes here
                    # response_from_ai = query_openjustice(english_text)
                    
                    # 3. Output logic (e.g., Twilio REST API to speak back)
    except Exception as e:
        print(f"Streaming Error: {e}")

if __name__ == "__main__":
    import uvicorn
    # Use port 8080 for Cloud Run compatibility
    uvicorn.run(app, host="0.0.0.0", port=8080)