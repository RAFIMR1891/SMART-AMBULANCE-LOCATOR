"""Gemini writes text only. It never touches the DB and never dispatches."""
import config
GUARD = ("You are an operations assistant for an ambulance dispatch centre. Use ONLY the facts "
         "provided. Do not invent values, diagnose patients, or assign triage categories. "
         "If information is missing, say so.\n\nFACTS:\n")

def ask_gemini(task, facts):
    if not config.GEMINI_API_KEY or not config.GEMINI_MODEL:
        return None, "Gemini is not configured (set GEMINI_API_KEY and GEMINI_MODEL)"
    try:
        from google import genai
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(model=config.GEMINI_MODEL, contents=f"{GUARD}{facts}\n\nTASK: {task}")
        return resp.text, None
    except Exception as e:
        return None, f"Gemini service unavailable: {type(e).__name__}"
