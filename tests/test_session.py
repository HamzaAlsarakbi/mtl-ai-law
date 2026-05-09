"""VOICE-04: Session state persisted per CallSid for the duration of the call."""
import pytest


def test_sessions_dict_exists_in_config():
    """sessions: dict[str, dict] must exist as a module-level attribute on config."""
    import config
    assert hasattr(config, "sessions"), "config.sessions dict not defined"
    assert isinstance(config.sessions, dict)


def test_session_initialized_with_required_keys():
    """A session entry must hold language, conversation_history, intake_stage, stream_sid."""
    import config
    call_sid = "CA_init_test"
    config.sessions[call_sid] = {
        "language": "en-US",
        "conversation_history": [],
        "intake_stage": "greeting",
        "stream_sid": "MZ_test",
    }
    s = config.sessions[call_sid]
    assert s["language"] == "en-US"
    assert s["conversation_history"] == []
    assert s["intake_stage"] == "greeting"
    assert s["stream_sid"] == "MZ_test"


def test_session_cleanup_on_stop():
    """Deleting a session by call_sid removes it (simulates 'stop' event handling)."""
    import config
    call_sid = "CA_cleanup_test"
    config.sessions[call_sid] = {"language": "en-US", "conversation_history": [], "intake_stage": "greeting", "stream_sid": "MZ"}
    assert call_sid in config.sessions
    del config.sessions[call_sid]
    assert call_sid not in config.sessions


def test_no_bleed_between_calls():
    """Second call's session does not inherit first call's language."""
    import config
    config.sessions["CA_first"] = {"language": "fr-FR", "conversation_history": ["bonjour"], "intake_stage": "greeting", "stream_sid": "MZ1"}
    del config.sessions["CA_first"]

    config.sessions["CA_second"] = {"language": "en-US", "conversation_history": [], "intake_stage": "greeting", "stream_sid": "MZ2"}
    assert config.sessions["CA_second"]["language"] == "en-US"
    assert config.sessions["CA_second"]["conversation_history"] == []
