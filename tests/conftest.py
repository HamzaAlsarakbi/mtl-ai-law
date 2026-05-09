"""Shared pytest fixtures for Phase 1 tests.

Fixtures intentionally avoid importing `config` at module level —
`config.py` initializes live Google Cloud clients on import.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_tts_client():
    """Mock Google TTS client returning a minimal MULAW WAV blob.

    The fake WAV places the 'data' marker at byte 36, followed by a
    4-byte length and 8 bytes of payload. _strip_wav_header should
    return exactly those 8 bytes.
    """
    client = MagicMock()
    fake_wav = b"\x00" * 36 + b"data" + b"\x08\x00\x00\x00" + b"\xd5" * 8
    response = MagicMock()
    response.audio_content = fake_wav
    client.synthesize_speech.return_value = response
    return client


@pytest.fixture
def mock_websocket():
    """AsyncMock FastAPI WebSocket. send_text is awaitable."""
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.fixture
def event_loop_for_tts():
    """Real asyncio event loop for run_coroutine_threadsafe tests.

    Named `event_loop_for_tts` (not `event_loop`) to avoid colliding
    with pytest-asyncio's reserved `event_loop` fixture name.
    Loop is started in a background thread so run_coroutine_threadsafe
    can dispatch to it.
    """
    import threading
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2.0)
    loop.close()


@pytest.fixture
def sample_session():
    """A fully-initialized session matching the sessions[call_sid] shape."""
    return {
        "language": "en-US",
        "conversation_history": [],
        "intake_stage": "greeting",
        "stream_sid": "MZ_test_stream_sid",
    }


@pytest.fixture(autouse=True)
def _isolate_sessions_dict():
    """Clear the sessions dict between tests so call_sid keys don't leak.

    Imports config lazily; if config is unimportable (missing creds),
    skip cleanup silently — the test will fail loudly on its own.
    """
    try:
        import config
        config.sessions.clear() if hasattr(config, "sessions") else None
    except Exception:
        pass
    yield
    try:
        import config
        config.sessions.clear() if hasattr(config, "sessions") else None
    except Exception:
        pass
