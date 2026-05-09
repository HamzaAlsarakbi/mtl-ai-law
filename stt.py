import queue
from google.cloud import speech
from config import speech_client, translate_client
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


def run_recognition_loop(audio_queue: queue.Queue, call_sid_ref: list) -> None:
    """
    Runs STT in a loop, restarting the stream as needed.

    call_sid_ref is a one-element list so the websocket handler can mutate it
    after this thread starts (call SID arrives on the 'start' event).
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
                        user_text = result.alternatives[0].transcript
                        confidence = result.alternatives[0].confidence
                        print(f"[stt] Detected: '{user_text}' (confidence: {confidence:.2f})", flush=True)

                        if confidence < 0.5 and len(result.alternatives) > 1:
                            alt = result.alternatives[1]
                            print(f"[stt]   Alternative: '{alt.transcript}' (confidence: {alt.confidence:.2f})", flush=True)

                        translated = translate_client.translate(user_text, target_language="en")
                        english_text = translated["translatedText"]
                        print(f"[stt] English: {english_text}", flush=True)

                        if call_sid_ref[0]:
                            gemini_response = query_gemini(english_text)
                            speak_response(call_sid_ref[0], gemini_response)
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
