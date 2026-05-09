import json
import base64
import os
import queue
import threading
from fastapi import FastAPI, WebSocket, Response
from google.cloud import speech, translate_v2 as translate
from google.cloud import aiplatform

app = FastAPI()


def _normalize_stream_host(raw_host: str) -> str:
    return raw_host.removeprefix("https://").removeprefix("http://").rstrip("/")

# Initialize Google Cloud Clients
speech_client = speech.SpeechClient()
translate_client = translate.Client()

# Replace with your actual public host name, without scheme.
DOMAIN = _normalize_stream_host(os.getenv("TWILIO_STREAM_HOST", "openjustice-agent-966017992454.us-central1.run.app"))

@app.post("/twilio-webhook")
async def twilio_webhook():
    """Initial entry point for Twilio calls."""
    stream_url = f"wss://{DOMAIN}/media"
    print(f"Twilio webhook requested, streaming to {stream_url}", flush=True)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Say>What up.</Say>
        <Connect>
            <Stream url="{stream_url}" />
        </Connect>
        <Pause length="600" />
    </Response>
    """
    print(f"TwiML response: {twiml.strip()}", flush=True)
    return Response(content=twiml, media_type="text/xml")

@app.websocket("/media")
async def websocket_endpoint(websocket: WebSocket):
    print(f"WebSocket handshake from {websocket.client}", flush=True)
    await websocket.accept()
    print("WebSocket connection established", flush=True)
    
    audio_queue = queue.Queue()

    def request_generator():
        print("Speech request generator started", flush=True)
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                print("Speech request generator closing", flush=True)
                return
            # print(f"Speech request generator got audio chunk: {len(chunk)} bytes", flush=True)
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def process_responses():
        # Focus on English; removing alternative_language_codes to avoid flaky language detection
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
            language_code="en-US",  # Fixed: was ar-SA
            alternative_language_codes=["fr-FR", "es-ES", "ar-SA"],
            enable_automatic_punctuation=True,
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            enable_voice_activity_events=True,
            voice_activity_timeout=speech.StreamingRecognitionConfig.VoiceActivityTimeout(
                speech_end_timeout={"seconds": 3}  # Increased from 2s for stability
            ),
            single_utterance=False,
        )

        while True:  # Keep restarting stream if it closes
            try:
                print("Starting Google streaming_recognize", flush=True)
                responses = speech_client.streaming_recognize(
                    config=streaming_config,
                    requests=request_generator(),
                )
                
                for response in responses:
                    if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE:
                        print("--- End of utterance detected ---", flush=True)
                        continue

                    for result in response.results:
                        if result.is_final:
                            user_text = result.alternatives[0].transcript
                            confidence = result.alternatives[0].confidence
                            print(f"Detected: '{user_text}' (confidence: {confidence:.2f})", flush=True)
                            
                            # Log alternatives if confidence is low for debugging
                            if confidence < 0.5 and len(result.alternatives) > 1:
                                print(f"  Alternative: '{result.alternatives[1].transcript}' (confidence: {result.alternatives[1].confidence:.2f})", flush=True)
                            
                            # Translation and OpenJustice logic
                            translated = translate_client.translate(user_text, target_language='en')
                            print(f"English: {translated['translatedText']}", flush=True)
                        elif result.is_interim:
                            # Log interim results for debugging
                            print(f"  [interim] {result.alternatives[0].transcript}", flush=True)
                            
            except Exception as e:
                # 499 is "cancelled" — expected when stream closes after Twilio stops sending audio
                error_code = getattr(e, 'code', None)
                if error_code == 499:
                    print("Speech stream closed (checking if more audio pending)", flush=True)
                    # Check if audio_queue still has data (more utterances coming)
                    # if audio_queue.empty():
                    #     print("No more audio, exiting speech thread", flush=True)
                        # break
                    # else:
                    print("Restarting stream for next utterance", flush=True)
                    continue
                else:
                    print(f"Speech Loop Error: {e}", flush=True)
                    break

    threading.Thread(target=process_responses, daemon=True).start()

    try:
        while True:
            message = await websocket.receive_text()
            # print(f"WebSocket message received: {message[:200]}", flush=True)
            data = json.loads(message)
            # print(f"WebSocket event: {data.get('event')}", flush=True)
            if data['event'] == 'media':
                payload = base64.b64decode(data['media']['payload'])
                # print(f"Media payload received: {len(payload)} bytes", flush=True)
                audio_queue.put(payload)
            if data['event'] == 'stop':
                print("Twilio stop event received", flush=True)
                break
    except Exception as e:
        print(f"WebSocket Loop Error: {e}", flush=True)
    finally:
        print("WebSocket closing, signaling speech thread", flush=True)
        audio_queue.put(None)

if __name__ == "__main__":
    import uvicorn
    # Use port 8080 for Cloud Run compatibility
    uvicorn.run(app, host="0.0.0.0", port=8080)