"""VOICE-01: /twilio-webhook returns TwiML with <Connect><Stream>."""
import pytest


def test_returns_connect_stream_twiml():
    """Webhook returns 200 with text/xml containing <Connect><Stream wss://...>."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    response = client.post("/twilio-webhook")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/xml")
    body = response.text
    assert "<Connect>" in body, "Must use <Connect> (bidirectional), not <Start>"
    assert "<Stream" in body
    assert "wss://" in body, "Stream URL must be wss:// for secure WebSocket"


def test_webhook_does_not_use_start_stream():
    """<Start><Stream> is one-way. We need <Connect><Stream> for bidirectional audio."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    response = client.post("/twilio-webhook")
    assert "<Start>" not in response.text, "Use <Connect> for bidirectional Media Streams"
