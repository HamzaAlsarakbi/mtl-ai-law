import os
from twilio.rest import Client as TwilioClient


def _normalize_host(raw: str) -> str:
    return raw.removeprefix("https://").removeprefix("http://").rstrip("/")


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "openjustice-hackathon-2026")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
DOMAIN = _normalize_host(os.getenv("TWILIO_STREAM_HOST", "openjustice-agent-966017992454.us-central1.run.app"))

twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
twilio_auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
twilio_client = TwilioClient(twilio_account_sid, twilio_auth_token) if twilio_account_sid else None

print(f"[config] project={PROJECT_ID} domain={DOMAIN}", flush=True)
print(f"[config] Twilio {'ready' if twilio_client else 'NOT configured'}", flush=True)
