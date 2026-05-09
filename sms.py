import os
from config import twilio_client

TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER", "")

_RESOURCES = {
    "en": (
        "JusticeLine Legal Resources:\n"
        "- Juripop (free legal help): juripop.org\n"
        "- Aide juridique (legal aid): 1-800-842-2213\n"
        "- Pro Bono Quebec: probonoquebec.ca"
    ),
    "fr": (
        "Ressources juridiques JusticeLine:\n"
        "- Juripop (aide gratuite): juripop.org\n"
        "- Aide juridique: 1-800-842-2213\n"
        "- Pro Bono Québec: probonoquebec.ca"
    ),
    "ar": (
        "موارد JusticeLine القانونية:\n"
        "- Juripop (مساعدة مجانية): juripop.org\n"
        "- المساعدة القانونية: 1-800-842-2213\n"
        "- Pro Bono Quebec: probonoquebec.ca"
    ),
    "es": (
        "Recursos legales JusticeLine:\n"
        "- Juripop (ayuda legal gratuita): juripop.org\n"
        "- Aide juridique: 1-800-842-2213\n"
        "- Pro Bono Quebec: probonoquebec.ca"
    ),
}


def _body_for_lang(language_code: str) -> str:
    prefix = language_code[:2].lower()
    return _RESOURCES.get(prefix, _RESOURCES["en"])


def send_sms_resources(to_number: str, language_code: str = "en-US") -> bool:
    if not twilio_client:
        print("[sms] Twilio client not initialized", flush=True)
        return False
    if not TWILIO_FROM:
        print("[sms] TWILIO_PHONE_NUMBER not set", flush=True)
        return False
    if not to_number:
        print("[sms] No caller number available", flush=True)
        return False
    try:
        body = _body_for_lang(language_code)
        msg = twilio_client.messages.create(body=body, from_=TWILIO_FROM, to=to_number)
        print(f"[sms] Sent to {to_number}: SID {msg.sid}", flush=True)
        return True
    except Exception as e:
        print(f"[sms] Error sending to {to_number}: {e}", flush=True)
        return False
