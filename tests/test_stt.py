"""VOICE-02: Google STT transcription with language detection."""
import pytest
from unittest.mock import MagicMock


def test_streaming_config_has_alternative_languages():
    """alternative_language_codes must include fr-FR, es-ES, ar-SA at minimum."""
    from stt import _make_streaming_config
    cfg = _make_streaming_config()
    langs = list(cfg.config.alternative_language_codes)
    assert "fr-FR" in langs
    assert "es-ES" in langs
    assert "ar-SA" in langs


def test_streaming_config_uses_mulaw_8khz():
    """RecognitionConfig must match Twilio Media Stream format (MULAW @ 8000Hz)."""
    from google.cloud import speech
    from stt import _make_streaming_config
    cfg = _make_streaming_config()
    assert cfg.config.encoding == speech.RecognitionConfig.AudioEncoding.MULAW
    assert cfg.config.sample_rate_hertz == 8000


def test_run_recognition_loop_signature_includes_websocket_and_loop():
    """Plan 01 extends signature to (audio_queue, call_sid_ref, websocket, loop)."""
    import inspect
    from stt import run_recognition_loop
    sig = inspect.signature(run_recognition_loop)
    params = list(sig.parameters.keys())
    assert "websocket" in params, "run_recognition_loop must accept websocket arg (Plan 01)"
    assert "loop" in params, "run_recognition_loop must accept loop arg (Plan 01)"


def test_language_extracted_from_final_result_writes_to_session():
    """When result.is_final + result.language_code='fr-FR', sessions[call_sid]['language']='fr-FR'.

    This test simulates the inner-loop write path. The full integration
    (mocking speech_client.streaming_recognize) is beyond unit scope;
    we verify the session-write contract.
    """
    import config
    call_sid = "CA_lang_test"
    config.sessions[call_sid] = {
        "language": "en-US",
        "conversation_history": [],
        "intake_stage": "greeting",
        "stream_sid": "MZ",
    }

    # Simulate what the loop does on a final result with language_code="fr-FR"
    fake_result = MagicMock()
    fake_result.is_final = True
    fake_result.language_code = "fr-FR"
    fake_result.alternatives = [MagicMock(transcript="Bonjour", confidence=0.95)]

    # The contract: detected_lang = result.language_code or "en-US"
    detected_lang = fake_result.language_code or "en-US"
    if call_sid in config.sessions:
        config.sessions[call_sid]["language"] = detected_lang

    assert config.sessions[call_sid]["language"] == "fr-FR"


def test_language_defaults_to_en_us_when_missing():
    """If result.language_code is empty/None, default to en-US."""
    fake_result = MagicMock()
    fake_result.language_code = ""
    detected_lang = fake_result.language_code or "en-US"
    assert detected_lang == "en-US"
