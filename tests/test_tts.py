"""VOICE-03: Google TTS MULAW output, WAV header stripped, mulaw injection over WebSocket."""
import json
import pytest
from unittest.mock import patch, MagicMock


def test_strip_wav_header_finds_data_marker():
    """_strip_wav_header returns bytes after 'data' chunk + 4-byte length."""
    from tts import _strip_wav_header
    payload = b"\xd5" * 8
    wav = b"\x00" * 36 + b"data" + b"\x08\x00\x00\x00" + payload
    assert _strip_wav_header(wav) == payload


def test_strip_wav_header_fallback_to_58():
    """If no 'data' marker, fall back to documented 58-byte skip."""
    from tts import _strip_wav_header
    wav = b"\x00" * 58 + b"\xd5" * 4
    assert _strip_wav_header(wav) == b"\xd5" * 4


def test_voice_for_french():
    """fr-FR maps to (fr-FR, fr-FR-Neural2-A)."""
    from tts import _voice_for_language
    lang_code, voice_name = _voice_for_language("fr-FR")
    assert lang_code == "fr-FR"
    assert voice_name == "fr-FR-Neural2-A"


def test_voice_for_spanish_uses_standard_not_neural2():
    """es-ES has no Neural2 voice — must use es-ES-Standard-A."""
    from tts import _voice_for_language
    lang_code, voice_name = _voice_for_language("es-ES")
    assert voice_name == "es-ES-Standard-A", "Neural2 unavailable for es-ES (per RESEARCH Pitfall 7)"


def test_voice_for_arabic_uses_standard():
    """ar-XA has no Neural2 voice — must use ar-XA-Standard-A."""
    from tts import _voice_for_language
    _, voice_name = _voice_for_language("ar-XA")
    assert voice_name == "ar-XA-Standard-A"


def test_voice_for_unknown_falls_back_to_english():
    """Unknown locale -> en-US-Neural2-C."""
    from tts import _voice_for_language
    _, voice_name = _voice_for_language("xx-XX")
    assert voice_name == "en-US-Neural2-C"


def test_synthesize_mulaw_returns_raw_bytes(mock_tts_client):
    """synthesize_mulaw configures MULAW @ 8000Hz and strips WAV header."""
    from google.cloud import texttospeech_v1 as texttospeech
    with patch("tts.tts_client", mock_tts_client):
        from tts import synthesize_mulaw
        result = synthesize_mulaw("hello", "en-US")

    assert result == b"\xd5" * 8, "Expected 8 bytes of payload after WAV strip"
    call_kwargs = mock_tts_client.synthesize_speech.call_args.kwargs
    audio_cfg = call_kwargs["audio_config"]
    assert audio_cfg.audio_encoding == texttospeech.AudioEncoding.MULAW
    assert audio_cfg.sample_rate_hertz == 8000


def test_speak_response_sends_correct_media_event(mock_tts_client, mock_websocket, event_loop_for_tts, sample_session):
    """speak_response: builds {event:'media', streamSid, media:{payload:b64}} and sends via run_coroutine_threadsafe."""
    import config
    call_sid = "CA_media_test"
    config.sessions[call_sid] = sample_session

    with patch("tts.tts_client", mock_tts_client):
        from tts import speak_response
        speak_response(call_sid, "Hello", mock_websocket, event_loop_for_tts)

    # send_text was called once with a JSON string
    assert mock_websocket.send_text.await_count >= 1
    sent_msg = mock_websocket.send_text.await_args.args[0]
    msg = json.loads(sent_msg)
    assert msg["event"] == "media"
    assert msg["streamSid"] == "MZ_test_stream_sid"
    assert "payload" in msg["media"]
    # payload must be base64 of the stripped mulaw bytes
    import base64
    assert base64.b64decode(msg["media"]["payload"]) == b"\xd5" * 8


def test_speak_response_skips_when_no_session(mock_tts_client, mock_websocket, event_loop_for_tts):
    """If sessions[call_sid] is missing, speak_response returns silently (no crash)."""
    with patch("tts.tts_client", mock_tts_client):
        from tts import speak_response
        speak_response("CA_nonexistent", "Hi", mock_websocket, event_loop_for_tts)

    mock_websocket.send_text.assert_not_called()


def test_speak_response_skips_when_no_stream_sid(mock_tts_client, mock_websocket, event_loop_for_tts):
    """If session has no stream_sid, speak_response returns silently (no crash)."""
    import config
    call_sid = "CA_no_stream"
    config.sessions[call_sid] = {"language": "en-US", "conversation_history": [], "intake_stage": "greeting", "stream_sid": None}

    with patch("tts.tts_client", mock_tts_client):
        from tts import speak_response
        speak_response(call_sid, "Hi", mock_websocket, event_loop_for_tts)

    mock_websocket.send_text.assert_not_called()
