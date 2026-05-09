"""Text-to-speech for Twilio Media Streams.

Synthesizes via Google Cloud TTS directly to MULAW @ 8000Hz (no
audioop/pydub/ffmpeg needed — RESEARCH critical deviation #1) and
injects the resulting audio into the live call by sending an
outbound `media` event over the same WebSocket the caller's audio
arrives on. Thread-safe send via asyncio.run_coroutine_threadsafe
because the STT loop that calls speak_response runs in a
threading.Thread, but the WebSocket lives on the asyncio loop
(RESEARCH Pattern 2 / Pitfall 2).
"""
import asyncio
import base64
import json

from google.cloud import texttospeech_v1 as texttospeech

from config import tts_client, sessions


# BCP-47 language code -> (TTS language_code, voice name).
# Neural2 voices are unavailable for es-ES and ar-XA as of 2026-05
# (RESEARCH Pitfall 7) — Standard-A is the documented fallback.
LANGUAGE_VOICES: dict[str, tuple[str, str]] = {
    "en-US": ("en-US", "en-US-Neural2-C"),
    "fr-FR": ("fr-FR", "fr-FR-Neural2-A"),
    "fr-CA": ("fr-CA", "fr-CA-Neural2-A"),
    "es-ES": ("es-ES", "es-ES-Standard-A"),
    "ar-XA": ("ar-XA", "ar-XA-Standard-A"),
    "ar-SA": ("ar-XA", "ar-XA-Standard-A"),
    "pt-BR": ("pt-BR", "pt-BR-Neural2-A"),
    "zh-CN": ("cmn-CN", "cmn-CN-Standard-A"),
    "hi-IN": ("hi-IN", "hi-IN-Neural2-A"),
}


def _voice_for_language(language_code: str) -> tuple[str, str]:
    """Look up (tts_language_code, voice_name); fall back to en-US."""
    return LANGUAGE_VOICES.get(language_code, LANGUAGE_VOICES["en-US"])


def _strip_wav_header(wav_bytes: bytes) -> bytes:
    """Return only the audio payload from a Google TTS MULAW WAV blob.

    Google TTS MULAW output is wrapped in a WAV container (~58 bytes
    of RIFF + fmt + fact + data headers). Twilio Media Streams
    requires raw mulaw — the header MUST be stripped or the caller
    hears a click/pop and garbled pitch (RESEARCH Pitfall 1).

    Parses for the `data` chunk marker rather than hard-coding 58,
    because chunk ordering is not strictly guaranteed.
    """
    idx = wav_bytes.find(b"data")
    if idx == -1:
        # Fallback: Twilio-blog-documented 58-byte header.
        return wav_bytes[58:]
    # 'data' (4 bytes) + chunk-length (4 bytes) precede the payload.
    return wav_bytes[idx + 8:]


def synthesize_mulaw(text: str, language_code: str = "en-US") -> bytes:
    """Synthesize text to raw mulaw 8000Hz bytes (WAV header stripped).

    Uses AudioEncoding.MULAW + sample_rate_hertz=8000 — Google TTS
    natively produces Twilio-compatible audio in one call, no
    post-processing needed (RESEARCH critical deviation #1).
    """
    voice_lang, voice_name = _voice_for_language(language_code)
    print(f"[tts] Synthesizing in {language_code} (voice={voice_name}): {text!r}", flush=True)
    response = tts_client.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(
            language_code=voice_lang,
            name=voice_name,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MULAW,
            sample_rate_hertz=8000,
        ),
    )
    return _strip_wav_header(response.audio_content)


def speak_response(call_sid: str, text: str, websocket, loop) -> None:
    """Synthesize TTS + inject audio over the Twilio Media Stream WebSocket.

    Called from the STT worker thread. Uses asyncio.run_coroutine_threadsafe
    to schedule the WebSocket send onto the asyncio event loop owned by
    main.py — calling `await websocket.send_text(...)` from this thread
    directly would corrupt asyncio internals (RESEARCH Pitfall 2).

    Twilio outbound media event uses streamSid (not callSid) as the
    routing key (RESEARCH Pitfall 3 / critical deviation #4).
    """
    session = sessions.get(call_sid)
    if not session:
        print(f"[tts] No session for {call_sid}, skipping", flush=True)
        return
    stream_sid = session.get("stream_sid")
    language = session.get("language", "en-US")
    if not stream_sid:
        print(f"[tts] No stream_sid for {call_sid}, skipping", flush=True)
        return

    try:
        mulaw_bytes = synthesize_mulaw(text, language)
        payload_b64 = base64.b64encode(mulaw_bytes).decode("ascii")
        msg = json.dumps({
            "event": "media",
            "streamSid": stream_sid,
            "media": {"payload": payload_b64},
        })
        future = asyncio.run_coroutine_threadsafe(websocket.send_text(msg), loop)
        future.result(timeout=5.0)
        print(f"[tts] Sent {len(mulaw_bytes)} mulaw bytes to stream {stream_sid}", flush=True)
        # Append assistant turn to conversation history (Plan 01 added user turn).
        session["conversation_history"].append(
            {"role": "assistant", "text": text, "lang": language}
        )
    except Exception as e:
        print(f"[tts] speak_response error: {e}", flush=True)
