"""JusticeLine — Twilio + Gemini Live API.

Audio pipeline (single bidirectional stream — no separate STT/TTS):
  Twilio MULAW 8kHz → upsample → PCM 16kHz → Gemini Live
  Gemini Live PCM 24kHz → downsample → MULAW 8kHz → Twilio
"""
import asyncio
import base64
import json
import os
import traceback
from importlib import import_module

try:
    import audioop
except ImportError:
    audioop = import_module("audioop_lts")  # Python 3.13+ fallback

from fastapi import FastAPI, Request, Response, WebSocket
from google import genai
from google.genai import errors, types

from config import PROJECT_ID, LOCATION, DOMAIN
from openjustice import query_openjustice
from sms import send_sms_resources

print("[main] JusticeLine starting (Gemini Live mode)", flush=True)

MODEL = "gemini-live-2.5-flash-native-audio"

SYSTEM_INSTRUCTION = """You are JusticeLine, a multilingual legal information AI assistant for Quebec, Canada.

CRITICAL RULES:
- You are NOT a lawyer. Provide general legal information only — never specific legal advice.
- For life-threatening emergencies, immediately tell the caller to hang up and dial 911.
- Detect the caller's language from their first words and respond in that language throughout the entire call.
- Keep every response under 80 words. Speak naturally and conversationally — no lists, no markdown.

CALL FLOW — follow this order exactly:
1. Greet the caller warmly. State this is not an emergency service (call 911 for emergencies). State you are an AI, not a lawyer. Ask them to describe their legal situation.
2. Listen. Then ask: "Where are you located? City or province?"
3. Ask ONE clarifying question if the situation is unclear.
4. Once you have both their situation and location, call query_legal_database immediately.
5. While the database is loading, say "Please wait a moment while I look up the relevant legal information."
6. When you receive the legal guidance, explain it in plain language in the caller's language.
7. Ask if they have follow-up questions. Answer up to 5.
8. Offer to send SMS resources: Juripop (juripop.org, free legal consultations) and Aide juridique (1-800-842-2213).
9. If they want SMS, call send_sms_resources.
10. Say a warm goodbye in the caller's language."""

_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="query_legal_database",
        description="Query the OpenJustice legal database. Call this when you have collected the caller's legal situation and location.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "situation": types.Schema(type=types.Type.STRING, description="The caller's legal situation (summarized in English)"),
                "jurisdiction": types.Schema(type=types.Type.STRING, description="The caller's location — city or province"),
            },
            required=["situation", "jurisdiction"],
        ),
    ),
    types.FunctionDeclaration(
        name="send_sms_resources",
        description="Send an SMS with legal resource phone numbers and links to the caller. Call this only after the caller has agreed to receive an SMS.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "language_code": types.Schema(
                    type=types.Type.STRING,
                    description="BCP-47 language code matching the caller's language, e.g. 'en', 'fr', 'ar', 'es'. Use 'en' if unsure.",
                ),
            },
        ),
    ),
])

app = FastAPI()

# CallSid → caller's From number (captured at webhook, consumed at WebSocket start)
_pending_callers: dict[str, str] = {}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "JusticeLine", "mode": "gemini-live"}


@app.post("/twilio-webhook")
async def twilio_webhook(request: Request):
    form = await request.form()
    call_sid = form.get("CallSid", "")
    from_number = form.get("From", "")
    if call_sid:
        _pending_callers[call_sid] = from_number
        print(f"[main] Incoming call: {call_sid} from {from_number}", flush=True)

    stream_url = f"wss://{DOMAIN}/media"
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}" />
    </Connect>
    <Pause length="600" />
</Response>"""
    return Response(content=twiml, media_type="text/xml")


def _audio_twilio_to_gemini(chunk: bytes, state) -> tuple[bytes, object]:
    """Twilio MULAW 8kHz → PCM 16kHz for Gemini Live input."""
    pcm_8k = audioop.ulaw2lin(chunk, 2)
    pcm_16k, new_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, state)
    return pcm_16k, new_state


def _audio_gemini_to_twilio(audio_data: bytes, state) -> tuple[str, object]:
    """Gemini Live PCM 24kHz → MULAW 8kHz base64 for Twilio."""
    pcm_8k, new_state = audioop.ratecv(audio_data, 2, 1, 24000, 8000, state)
    mulaw = audioop.lin2ulaw(pcm_8k, 2)
    return base64.b64encode(mulaw).decode("utf-8"), new_state


async def _handle_tool_call(fc_name: str, fc_args: dict, caller_number: str | None) -> str:
    loop = asyncio.get_running_loop()
    if fc_name == "query_legal_database":
        situation = fc_args.get("situation", "")
        jurisdiction = fc_args.get("jurisdiction", "")
        print(f"[tool] query_legal_database: {situation[:80]!r} | {jurisdiction!r}", flush=True)
        result = await loop.run_in_executor(None, query_openjustice, situation, jurisdiction)
        return result
    if fc_name == "send_sms_resources":
        language_code = fc_args.get("language_code") or "en"
        print(f"[tool] send_sms_resources: to={caller_number} lang={language_code}", flush=True)
        if caller_number:
            sent = await loop.run_in_executor(None, send_sms_resources, caller_number, language_code)
            return "SMS sent successfully" if sent else "SMS could not be delivered"
        return "No caller phone number available"
    return f"Unknown function: {fc_name}"


@app.websocket("/media")
async def media_stream(websocket: WebSocket):
    await websocket.accept()
    print("[main] WebSocket accepted", flush=True)

    call_sid: str | None = None
    stream_sid: str | None = None
    caller_number: str | None = None
    upsample_state = None
    downsample_state = None
    greeted = False

    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    live_config = types.LiveConnectConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        response_modalities=["AUDIO"],
        tools=[_TOOLS],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=live_config) as session:

            async def _receiver():
                nonlocal downsample_state
                try:
                    async for response in session.receive():
                        sc = response.server_content
                        if sc:
                            if sc.input_transcription and sc.input_transcription.text:
                                print(f"[user] {sc.input_transcription.text}", flush=True)
                            if sc.output_transcription and sc.output_transcription.text:
                                print(f"[bot]  {sc.output_transcription.text}", flush=True)
                            if sc.model_turn:
                                for part in sc.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        b64, downsample_state = _audio_gemini_to_twilio(
                                            part.inline_data.data, downsample_state
                                        )
                                        if stream_sid:
                                            await websocket.send_json({
                                                "event": "media",
                                                "streamSid": stream_sid,
                                                "media": {"payload": b64},
                                            })
                            if sc.interrupted:
                                print("[gemini] turn interrupted by caller", flush=True)

                        if response.tool_call:
                            for fc in response.tool_call.function_calls:
                                result = await _handle_tool_call(fc.name, dict(fc.args), caller_number)
                                await session.send_tool_response(
                                    function_responses=[types.FunctionResponse(
                                        name=fc.name,
                                        id=fc.id,
                                        response={"result": result},
                                    )]
                                )

                        if response.go_away:
                            print(f"[gemini] go_away: {response.go_away}", flush=True)
                            return
                except asyncio.CancelledError:
                    raise
                except errors.APIError as e:
                    print(f"[gemini] APIError: code={getattr(e, 'code', None)} {e}", flush=True)
                except Exception:
                    print("[gemini] receiver crashed:", flush=True)
                    traceback.print_exc()

            receiver_task = asyncio.create_task(_receiver())

            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    event = data.get("event")

                    if event == "start":
                        call_sid = data["start"]["callSid"]
                        stream_sid = data["start"]["streamSid"]
                        caller_number = _pending_callers.pop(call_sid, None)
                        print(f"[main] start: {call_sid} stream={stream_sid} from={caller_number}", flush=True)

                    elif event == "media":
                        if receiver_task.done():
                            print("[main] Gemini receiver exited, closing call", flush=True)
                            break
                        if not greeted:
                            greeted = True
                            await session.send_client_content(
                                turns=types.Content(
                                    role="user",
                                    parts=[types.Part(text="The caller just connected. Begin step 1 now: greet them, state this is not 911 and you are an AI not a lawyer, then ask them to describe their legal situation.")],
                                ),
                                turn_complete=True,
                            )
                        chunk = base64.b64decode(data["media"]["payload"])
                        pcm_16k, upsample_state = _audio_twilio_to_gemini(chunk, upsample_state)
                        if pcm_16k:
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000"),
                            )

                    elif event == "stop":
                        print(f"[main] stop event for {call_sid}", flush=True)
                        break

            except Exception:
                print("[main] WebSocket error:", flush=True)
                traceback.print_exc()
            finally:
                receiver_task.cancel()
                try:
                    await receiver_task
                except (asyncio.CancelledError, Exception):
                    pass
                print(f"[main] Session closed for {call_sid}", flush=True)
    except Exception:
        print("[main] Gemini Live connection failed:", flush=True)
        traceback.print_exc()
        try:
            await websocket.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    import sys

    # PORT 8080 is required for Cloud Run, but we add timeout tweaks for local/ngrok
    port = int(os.getenv("PORT", "8080"))

    try:
        uvicorn.run(
            "main:app",             # Using import string for better signal handling
            host="0.0.0.0", 
            port=port,
            # Vital for Gemini Live: Prevents the server from killing "long" connections
            timeout_keep_alive=75,  
            # Helps maintain heartbeats over the ngrok tunnel
            ws_ping_interval=20,    
            ws_ping_timeout=20,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n[main] Shutdown requested (KeyboardInterrupt)", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"[main] uvicorn.run raised an exception: {e}", flush=True)
        raise