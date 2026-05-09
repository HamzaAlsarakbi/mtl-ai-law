from config import gemini_model


def query_gemini(user_text: str) -> str:
    """Query Gemini for a legal response based on user input."""
    try:
        print(f"[llm] Querying Gemini with: {user_text}", flush=True)
        response = gemini_model.generate_content(
            f"""You are a helpful legal information assistant for Montreal.
The user asked: {user_text}

Provide a brief, conversational response (under 100 words) addressing their legal question.
Do not provide legal advice; provide general legal information and suggest they consult a lawyer."""
        )
        result = response.text.strip()
        print(f"[llm] Gemini response: {result}", flush=True)
        return result
    except Exception as e:
        print(f"[llm] Gemini error: {e}", flush=True)
        return "I'm having trouble processing that. Could you rephrase your question?"
