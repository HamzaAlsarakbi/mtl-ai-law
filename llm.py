"""Stage-aware intake flow and Gemini orchestration for JusticeLine.

Call stages (stored in session["intake_stage"]):
  greeting   → played on connect, waiting for first utterance
  situation  → situation collected, asking for location
  jurisdiction → location collected, asking one clarifying question
  clarifying → clarifying answer received, saying "please wait"
  waiting_oj → "please wait" spoken; stt.py calls OJ and transitions to explaining
  explaining → OJ result spoken + SMS offer; waiting for follow-up or SMS reply
  followup   → answering follow-up questions
  sms_offer  → user asked about SMS / system offered; waiting for yes/no
  done       → goodbye spoken, call winding down
"""

from config import gemini_model, translate_client, sessions

# BCP-47 prefix → Google Translate 2-char code
_TRANSLATE_LANG = {
    "fr": "fr", "ar": "ar", "es": "es",
    "pt": "pt", "zh": "zh-CN", "hi": "hi",
    "de": "de", "it": "it", "ru": "ru",
}

# Keywords (in any translated English) that signal "yes" to SMS offer
_YES_WORDS = {"yes", "yeah", "sure", "please", "ok", "okay", "oui", "si", "نعم", "send", "text", "sms"}


def _translate(text: str, language_code: str) -> str:
    """Translate English canned text into the caller's language."""
    prefix = language_code[:2].lower()
    if prefix == "en":
        return text
    target = _TRANSLATE_LANG.get(prefix, prefix)
    try:
        result = translate_client.translate(text, target_language=target)
        return result["translatedText"]
    except Exception as e:
        print(f"[llm] translate error ({language_code}): {e}", flush=True)
        return text


def _gemini(prompt: str, fallback: str = "") -> str:
    try:
        resp = gemini_model.generate_content(prompt)
        return resp.text.strip()
    except Exception as e:
        print(f"[llm] Gemini error: {e}", flush=True)
        return fallback


def _lang_instruction(language_code: str) -> str:
    """Return Gemini instruction for response language."""
    mapping = {
        "fr-FR": "French", "fr-CA": "French (Canadian)",
        "ar-SA": "Arabic", "ar-XA": "Arabic",
        "es-ES": "Spanish", "pt-BR": "Portuguese (Brazilian)",
        "zh-CN": "Simplified Chinese", "hi-IN": "Hindi",
        "de-DE": "German", "it-IT": "Italian", "ru-RU": "Russian",
    }
    lang_name = mapping.get(language_code, "English")
    return f'Respond ONLY in {lang_name} (BCP-47: "{language_code}"). Do not add explanations about the language.'




def handle_stage(call_sid: str, english_text: str, language_code: str) -> str:
    """Process one user utterance and advance the call stage.

    Returns the response the system should speak (already in target language).
    Mutates session["intake_stage"] as a side effect.
    """
    session = sessions.get(call_sid)
    if not session:
        return _translate("I'm sorry, there was a technical error. Please call back.", language_code)

    stage = session.get("intake_stage", "situation")
    print(f"[llm] stage={stage} lang={language_code} input={english_text[:60]!r}", flush=True)

    if stage == "situation":
        session["situation_raw"] = english_text
        session["intake_stage"] = "jurisdiction"
        return _translate(
            "Thank you. Where are you located? Please tell me your city or province.",
            language_code,
        )

    if stage == "jurisdiction":
        session["jurisdiction"] = english_text
        session["intake_stage"] = "clarifying"
        return _ask_clarifying(session, language_code)

    if stage == "clarifying":
        # Fold clarifying answer into the situation summary
        session["situation_raw"] = (
            session.get("situation_raw", "") + f". Additional detail: {english_text}"
        )
        session["intake_stage"] = "waiting_oj"
        return _translate(
            "Thank you. Please wait a moment while I look up the relevant legal information.",
            language_code,
        )

    if stage in ("explaining", "followup"):
        session["followup_count"] = session.get("followup_count", 0) + 1
        if session.get("followup_count", 0) > 5:
            session["intake_stage"] = "done"
            return _translate("Thank you for calling JusticeLine. Take care, and goodbye.", language_code)
        session["intake_stage"] = "followup"
        return _answer_followup(english_text, session, language_code)

    if stage == "sms_offer":
        session["intake_stage"] = "done"
        if _user_said_yes(english_text):
            session["send_sms"] = True
            return _translate(
                "I'll send you the resources by text message right away. "
                "Thank you for calling JusticeLine. Take care, and goodbye.",
                language_code,
            )
        return _translate(
            "No problem. Remember: Juripop at juripop.org and Aide juridique at 1-800-842-2213 "
            "are both free. Thank you for calling JusticeLine. Goodbye.",
            language_code,
        )

    # done / unknown
    return _translate("Thank you for calling JusticeLine. Goodbye.", language_code)


def generate_oj_explanation(oj_result: str, session: dict) -> str:
    """Summarize OJ result in caller's language + offer SMS. Sets stage to sms_offer."""
    language_code = session.get("language", "en-US")
    session["intake_stage"] = "sms_offer"

    prompt = f"""{_lang_instruction(language_code)}

You are JusticeLine, a legal information assistant for Quebec, Canada.
A legal database returned this guidance for a caller:

{oj_result}

Instructions:
1. Summarize the guidance in plain, accessible language — under 120 words.
2. End with: ask the caller if they would like SMS resources for free legal help (Juripop, Aide juridique).
3. Do NOT provide legal advice — provide general legal information only.
4. Speak directly to the caller ("you", "your situation")."""

    fallback = _translate(
        f"{oj_result[:300]}... "
        "Would you like me to send you SMS resources for free legal help such as Juripop and Aide juridique?",
        language_code,
    )
    return _gemini(prompt, fallback)


def _ask_clarifying(session: dict, language_code: str) -> str:
    situation = session.get("situation_raw", "")
    jurisdiction = session.get("jurisdiction", "")
    prompt = f"""{_lang_instruction(language_code)}

You are a legal intake assistant for Quebec, Canada.
A caller has described:
- Situation: {situation}
- Location: {jurisdiction}

Ask ONE concise clarifying question (under 25 words) to better understand the legal issue.
Output only the question — no preamble, no explanation."""
    return _gemini(prompt, _translate("Could you tell me a bit more about what happened?", language_code))


def _answer_followup(question: str, session: dict, language_code: str) -> str:
    oj_result = session.get("oj_result", "")
    situation = session.get("situation_raw", "")
    prompt = f"""{_lang_instruction(language_code)}

You are JusticeLine, a legal information assistant (not a lawyer) for Quebec, Canada.

Context:
- Caller situation: {situation}
- Legal guidance retrieved: {oj_result}
- Follow-up question (English): {question}

Answer briefly (under 80 words) in plain, conversational language.
Do not provide specific legal advice — provide general legal information only.
If appropriate, remind them free help is available at juripop.org."""
    return _gemini(
        prompt,
        _translate("I'm sorry, I'm having difficulty with that. Please consult a lawyer for advice specific to your case.", language_code),
    )


def _user_said_yes(english_text: str) -> bool:
    words = set(english_text.lower().split())
    return bool(words & _YES_WORDS)
