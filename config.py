import os
from google.cloud import speech, translate_v2 as translate, texttospeech_v1 as texttospeech
import vertexai
from vertexai.generative_models import GenerativeModel
from twilio.rest import Client as TwilioClient


def _normalize_stream_host(raw_host: str) -> str:
    return raw_host.removeprefix("https://").removeprefix("http://").rstrip("/")


print("[config] Initializing Google Cloud clients...", flush=True)
speech_client = speech.SpeechClient()
translate_client = translate.Client()
tts_client = texttospeech.TextToSpeechClient()
print("[config] Google Cloud clients ready", flush=True)

project_id = os.getenv("GCP_PROJECT_ID", "")
print(f"[config] Initializing Vertex AI for project: {project_id!r}", flush=True)
vertexai.init(project=project_id)
gemini_model = GenerativeModel("gemini-2.5-flash")
print("[config] Gemini model ready", flush=True)

twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
twilio_client = TwilioClient(twilio_account_sid, twilio_auth_token) if twilio_account_sid else None
print(f"[config] Twilio client {'ready' if twilio_client else 'NOT configured (missing TWILIO_ACCOUNT_SID)'}", flush=True)

DOMAIN = _normalize_stream_host(os.getenv("TWILIO_STREAM_HOST", "openjustice-agent-966017992454.us-central1.run.app"))
print(f"[config] Stream domain: {DOMAIN}", flush=True)

# Session state keyed by Twilio CallSid. Initialized on 'start' event
# in main.py, cleaned up on 'stop'. Module-level so any thread/module
# can read/write via `from config import sessions` (per D-01).
sessions: dict[str, dict] = {}
print(f"[config] Sessions dict initialized (capacity: unlimited, single Cloud Run instance)", flush=True)
