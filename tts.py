from google.cloud import texttospeech_v1 as texttospeech
from config import tts_client, twilio_client


def speak_response(call_sid: str, text: str) -> None:
    """Convert text to speech and play it back on the Twilio call."""
    if not twilio_client:
        print("[tts] Twilio client not configured, skipping TTS", flush=True)
        return

    try:
        print(f"[tts] Generating TTS for: {text}", flush=True)
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Neural2-C",
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
        )
        tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )

        print(f"[tts] Playing response on call {call_sid}", flush=True)
        twilio_client.calls(call_sid).update(twiml=f"<Response><Say>{text}</Say></Response>")
        print("[tts] Response spoken", flush=True)
    except Exception as e:
        print(f"[tts] TTS/Twilio error: {e}", flush=True)
