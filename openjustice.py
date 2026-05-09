import os
import requests

OJ_BASE = os.getenv("OPENJUSTICE_BASE_URL", "https://api.openjustice.ai/api")
OJ_KEY = os.getenv("OPENJUSTICE_API_KEY", "")
OJ_FLOW_ID = os.getenv("OPENJUSTICE_DIALOG_FLOW_ID", "45ebe699-1ff4-45c6-b82c-eb565e153ee6")

_FALLBACK = (
    "Based on what you've described, you may have grounds to pursue a legal remedy. "
    "I recommend consulting a lawyer for advice specific to your situation. "
    "Juripop offers free legal consultations at juripop.org, "
    "and Aide juridique can be reached at 1-800-842-2213."
)


def query_openjustice(situation: str, jurisdiction: str) -> str:
    if not OJ_FLOW_ID:
        print("[oj] OPENJUSTICE_DIALOG_FLOW_ID not set — returning fallback", flush=True)
        return _FALLBACK

    message = f"Situation: {situation}\nJurisdiction / Location: {jurisdiction}"
    print(f"[oj] Querying dialog flow {OJ_FLOW_ID}: {message[:120]!r}", flush=True)
    try:
        resp = requests.post(
            f"{OJ_BASE}/dialog-flow-executions/run",
            headers={
                "Authorization": f"Bearer {OJ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "dialogFlowId": OJ_FLOW_ID,
                "messages": [{"content": message}],
                "model": "gemini-2.5-flash",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        result = (data.get("response") or "").strip()
        print(f"[oj] Got response ({len(result)} chars): {result[:200]}", flush=True)
        return result or _FALLBACK
    except Exception as e:
        print(f"[oj] Error: {e}", flush=True)
        return _FALLBACK
