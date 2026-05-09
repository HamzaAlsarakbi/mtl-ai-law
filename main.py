"""JusticeLine — Twilio + Gemini Live API.

Audio pipeline (single bidirectional stream — no separate STT/TTS):
  Twilio MULAW 8kHz → upsample → PCM 16kHz → Gemini Live
  Gemini Live PCM 24kHz → downsample → MULAW 8kHz → Twilio
"""
import asyncio
import base64
import json
import os

try:
    import audioop
except ImportError:
    import audioop_lts as audioop  # Python 3.13+ fallback

from fastapi import FastAPI, Request, Response, WebSocket
from google import genai
from google.genai import types

from config import PROJECT_ID, LOCATION, DOMAIN
from openjustice import query_openjustice
from sms import send_sms_resources

print("[main] JusticeLine starting (Gemini Live mode)", flush=True)

MODEL = "gemini-2.0-flash-live-001"

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
        description="Send an SMS with legal resource phone numbers and links to the caller",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={},
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
        print(f"[tool] send_sms_resources: to={caller_number}", flush=True)
        if caller_number:
            sent = await loop.run_in_executor(None, send_sms_resources, caller_number)
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
    audio_buffer = bytearray()
    upsample_state = None
    downsample_state = None

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
    )

    async with client.aio.live.connect(model=MODEL, config=live_config) as session:

        async def _receiver():
            nonlocal downsample_state, stream_sid
            try:
                async for response in session.receive():
                    # Audio from Gemini → forward to Twilio
                    if (response.server_content
                            and response.server_content.model_turn):
                        for part in response.server_content.model_turn.parts:
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

                    # Function call from Gemini → execute → return result
                    if response.tool_call:
                        for fc in response.tool_call.function_calls:
                            result = await _handle_tool_call(fc.name, dict(fc.args), caller_number)
                            await session.send(
                                input=types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=fc.name,
                                        id=fc.id,
                                        response={"result": result},
                                    )]
                                )
                            )
            except Exception as e:
                print(f"[gemini] receiver error: {e}", flush=True)

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
                    chunk = base64.b64decode(data["media"]["payload"])
                    pcm_16k, upsample_state = _audio_twilio_to_gemini(chunk, upsample_state)
                    audio_buffer.extend(pcm_16k)
                    # Send ~300ms chunks (9600 bytes @ 16kHz stereo-mono)
                    if len(audio_buffer) >= 9600:
                        await session.send(
                            input={"data": bytes(audio_buffer), "mime_type": "audio/pcm;rate=16000"},
                            end_of_turn=False,
                        )
                        audio_buffer.clear()

                elif event == "stop":
                    print(f"[main] stop event for {call_sid}", flush=True)
                    break

        except Exception as e:
            print(f"[main] WebSocket error: {e}", flush=True)
        finally:
            receiver_task.cancel()
            print(f"[main] Session closed for {call_sid}", flush=True)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
