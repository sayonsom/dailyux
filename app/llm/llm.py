from typing import List, Optional, Dict, Any
from app.settings import settings
import json, re

# Singleton
_llm = None


def _import_llm():
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI  # type: ignore
        return ChatGoogleGenerativeAI
    except Exception:
        return None


def get_llm():
    """Return a cached LLM client or None if unavailable or disabled by config."""
    if (settings.LLM_MODE or "client").lower() != "server":
        return None
    global _llm
    if _llm is None:
        ChatGoogleGenerativeAI = _import_llm()
        if ChatGoogleGenerativeAI is None:
            return None
        _llm = ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
            temperature=0.2,
            convert_system_message_to_human=True,  # Gemini doesn't use system role
        )
    return _llm


def _safe_text(resp) -> str:
    try:
        text = getattr(resp, "content", None)
        return text if isinstance(text, str) else (str(resp) if resp is not None else "")
    except Exception:
        return ""


# ---------------- Client-first prompts and parsers ----------------

def build_bullets_prompt(prompt: str, count: int = 3) -> str:
    """Return a model-agnostic prompt for generating short numbered bullets."""
    return (
        prompt
        + f"\n\nRespond with {count} short, numbered bullets. Keep each under 12 words."
    )


def parse_bullets(text: str, count: int = 3) -> List[str]:
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    cleaned: List[str] = []
    for l in lines:
        l2 = l.lstrip("-• ")
        # remove leading numbers like "1.", "1)"
        if len(l2) > 2 and l2[0].isdigit() and l2[1] in ".)":
            # strip leading number and punctuation
            i = 1
            while i < len(l2) and l2[i] in ")}. ":
                i += 1
            l2 = l2[i:]
        cleaned.append(l2)
    out: List[str] = []
    for c in cleaned:
        if c:
            out.append(c)
    return out[:count]


def generate_bullets(prompt: str, count: int = 3) -> List[str]:
    llm = get_llm()
    if not llm:
        # Fallback deterministic placeholders
        return [
            "Protect 60m deep work",
            "Batch messages mid-day",
            "Plan unwind window",
        ][:count]
    try:
        full_prompt = build_bullets_prompt(prompt, count)
        resp = llm.invoke(full_prompt)
        text = _safe_text(resp)
        bullets = parse_bullets(text, count)
        return bullets if bullets else ["Short plan point 1", "Short plan point 2", "Short plan point 3"][:count]
    except Exception:
        return [
            "Protect 60m deep work",
            "Batch messages mid-day",
            "Plan unwind window",
        ][:count]


# NL interpretation helpers (simple)

def build_interpret_nl_prompt(kind: str, params: Dict[str, Any]) -> str:
    if kind == "interpret_nl":
        utt = params.get("utterance", "")
        return (
            "You are a planner assistant. Interpret the user's utterance into a JSON action.\n"
            "Possible actions: change_theme, change_tone, add_invitees, remove_invitees, change_time, change_venue.\n"
            "Return strictly a JSON object with keys: type (string), and relevant fields.\n"
            f"Utterance: {utt}\n"
        )
    return ""


def interpret_nl(utterance: str) -> Optional[Dict[str, Any]]:
    llm = get_llm()
    if not llm:
        return None
    try:
        prompt = build_interpret_nl_prompt("interpret_nl", {"utterance": utterance})
        resp = llm.invoke(prompt)
        text = _safe_text(resp)
        import json
        return json.loads(text)
    except Exception:
        return None
