import queue
from google.cloud import speech
from config import speech_client, translate_client, sessions
from llm import query_gemini
from tts import speak_response


def _make_streaming_config() -> speech.StreamingRecognitionConfig:
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.MULAW,
        sample_rate_hertz=8000,
        language_code="en-US",
        alternative_language_codes=["fr-FR", "es-ES", "ar-SA"],
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


def run_recognition_loop(audio_queue: queue.Queue, call_sid_ref: list, websocket, loop) -> None:
    """
    Runs STT in a loop, restarting the stream as needed.

    call_sid_ref is a one-element list so the websocket handler can mutate it
    after this thread starts (call SID arrives on the 'start' event).

    websocket + loop are passed through to speak_response so it can use
    asyncio.run_coroutine_threadsafe to send audio back over the WebSocket
    from this worker thread (per RESEARCH Pattern 2 — never call
    await websocket.send_text from a non-asyncio thread).
    """
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
                    print("[stt] --- End of utterance detected ---", flush=True)
                    continue

                for result in response.results:
                    if result.is_final:
                        call_sid = call_sid_ref[0]

                        # Suppress processing while TTS is playing to break feedback loop.
                        # STT hears our own TTS output — without this guard the system
                        # transcribes its own speech and responds forever.
                        if call_sid and sessions.get(call_sid, {}).get("is_speaking"):
                            print("[stt] Suppressed (TTS playing), discarding result", flush=True)
                            continue

                        user_text = result.alternatives[0].transcript
                        confidence = result.alternatives[0].confidence
                        detected_lang = result.language_code or "en-US"
                        print(f"[stt] Detected: '{user_text}' lang={detected_lang} (conf: {confidence:.2f})", flush=True)

                        # Write detected language to session immediately (per D-02).
                        if call_sid and call_sid in sessions:
                            sessions[call_sid]["language"] = detected_lang
                            sessions[call_sid]["conversation_history"].append(
                                {"role": "user", "text": user_text, "lang": detected_lang}
                            )

                        if confidence < 0.5 and len(result.alternatives) > 1:
                            alt = result.alternatives[1]
                            print(f"[stt]   Alternative: '{alt.transcript}' (conf: {alt.confidence:.2f})", flush=True)

                        translated = translate_client.translate(user_text, target_language="en")
                        english_text = translated["translatedText"]
                        print(f"[stt] English: {english_text}", flush=True)

                        if call_sid:
                            gemini_response = query_gemini(english_text, detected_lang)
                            speak_response(call_sid, gemini_response, websocket, loop)
                        else:
                            print("[stt] No call SID yet, skipping response", flush=True)

                    elif result.is_interim:
                        print(f"[stt]   [interim] {result.alternatives[0].transcript}", flush=True)

        except Exception as e:
            error_code = getattr(e, "code", None)
            if error_code == 499:
                print("[stt] Speech stream closed (checking if more audio pending)", flush=True)
                import time
                time.sleep(0.5)
                continue
            else:
                print(f"[stt] Speech loop error: {e}", flush=True)
                break
