import queue
from google.cloud import speech
from config import speech_client, translate_client, sessions
from llm import handle_stage, generate_oj_explanation
from openjustice import query_openjustice
from sms import send_sms_resources
from tts import speak_response


def _make_streaming_config() -> speech.StreamingRecognitionConfig:
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
        sample_rate_hertz=8000,
        language_code="en-US",
        alternative_language_codes=["fr-CA", "fr-FR", "ar-SA", "ar-XA", "es-ES", "pt-BR", "zh-CN", "hi-IN"],
        enable_automatic_punctuation=True,
    )
    return speech.StreamingRecognitionConfig(
        config=config,
        enable_voice_activity_events=True,
        voice_activity_timeout=speech.StreamingRecognitionConfig.VoiceActivityTimeout(
            speech_end_timeout={"seconds": 3}
        ),
        single_utterance=False,
    )


def _request_generator(audio_queue: queue.Queue):
    print("[stt] Speech request generator started", flush=True)
    while True:
        chunk = audio_queue.get()
        if chunk is None:
            print("[stt] Speech request generator closing", flush=True)
            return
        yield speech.StreamingRecognizeRequest(audio_content=chunk)


def _to_english(text: str) -> str:
    """Translate any text to English for stage processing."""
    try:
        result = translate_client.translate(text, target_language="en")
        return result["translatedText"]
    except Exception:
        return text


def _process_utterance(call_sid: str, user_text: str, detected_lang: str, websocket, loop) -> None:
    """Handle one complete utterance through the intake state machine."""
    print(f"[stt] Processing utterance for {call_sid}: {user_text!r} (lang={detected_lang})", flush=True)
    english_text = _to_english(user_text)
    print(f"[stt] English: {english_text!r}", flush=True)

    session = sessions.get(call_sid)
    if not session:
        print(f"[stt] No session for {call_sid}", flush=True)
        return

    # Update language from this utterance (more accurate over time)
    session["language"] = detected_lang

    # Append user turn to history
    session["conversation_history"].append(
        {"role": "user", "text": user_text, "lang": detected_lang}
    )

    # Get stage response
    response = handle_stage(call_sid, english_text, detected_lang)
    speak_response(call_sid, response, websocket, loop, language_code=detected_lang)

    # If stage just moved to waiting_oj, call OpenJustice now (blocking — "please wait" already spoken)
    session = sessions.get(call_sid)
    if session and session.get("intake_stage") == "waiting_oj":
        oj_result = query_openjustice(
            session.get("situation_raw", ""),
            session.get("jurisdiction", ""),
        )
        session["oj_result"] = oj_result
        session["intake_stage"] = "explaining"
        explanation = generate_oj_explanation(oj_result, session)
        speak_response(call_sid, explanation, websocket, loop, language_code=detected_lang)

    # If user agreed to SMS, send it
    session = sessions.get(call_sid)
    if session and session.pop("send_sms", False):
        caller_number = session.get("caller_number")
        lang = session.get("language", "en-US")
        send_sms_resources(caller_number, lang)


def run_recognition_loop(audio_queue: queue.Queue, call_sid_ref: list, websocket, loop) -> None:
    """STT worker thread — streams audio to Google, processes final transcripts."""
    print("[stt] Recognition loop starting", flush=True)
    streaming_config = _make_streaming_config()

    while True:
        try:
            print("[stt] Starting Google streaming_recognize", flush=True)
            responses = speech_client.streaming_recognize(
                config=streaming_config,
                requests=_request_generator(audio_queue),
            )

            for response in responses:
                if response.speech_event_type == speech.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE:
                    print("[stt] --- End of utterance ---", flush=True)
                    continue

                for result in response.results:
                    if result.is_final:
                        call_sid = call_sid_ref[0]

                        session_state = sessions.get(call_sid, {})

                        # Suppress while TTS is playing (echo guard)
                        if call_sid and session_state.get("is_speaking"):
                            print("[stt] Suppressed (TTS playing)", flush=True)
                            continue

                        # Suppress during greeting — caller speech would collide
                        if call_sid and session_state.get("intake_stage") == "greeting":
                            print("[stt] Suppressed (greeting in progress)", flush=True)
                            continue

                        user_text = result.alternatives[0].transcript
                        confidence = result.alternatives[0].confidence
                        detected_lang = result.language_code or "en-US"
                        print(f"[stt] Final: {user_text!r} lang={detected_lang} conf={confidence:.2f}", flush=True)

                        if call_sid:
                            _process_utterance(call_sid, user_text, detected_lang, websocket, loop)
                        else:
                            print("[stt] No call SID yet, skipping", flush=True)

                    elif result.is_interim:
                        print(f"[stt]   [interim] {result.alternatives[0].transcript!r}", flush=True)

        except Exception as e:
            error_code = getattr(e, "code", None)
            if error_code == 499:
                print("[stt] Speech stream closed (CANCELLED) — restarting", flush=True)
                import time; time.sleep(0.5)
                continue
            else:
                print(f"[stt] Fatal speech loop error: {e}", flush=True)
                break
