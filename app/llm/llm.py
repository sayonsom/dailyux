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
            l2 = l2[2:].strip()
        cleaned.append(l2)
    out: List[str] = []
    for c in cleaned:
        if c and c not in out:
            out.append(c)
    return out[:count]


def generate_bullets(prompt: str, count: int = 3) -> List[str]:
    """Return up to `count` concise bullets from the LLM.
    If server LLMs are disabled, return an empty list so callers can provide client results.
    """
    try:
        llm = get_llm()
        if llm is None:
            return []
        full_prompt = build_bullets_prompt(prompt, count=count)
        resp = llm.invoke(full_prompt)
        text = _safe_text(resp)
        return parse_bullets(text, count=count)
    except Exception:
        return []

# ---------------- NL Interpreter ----------------

NL_SCHEMA = (
    "Decide the intent of this instruction for a day-planner/birthday-planner app. "
    "Return JSON only. Keys: type: one of [start_birthday_plan, edit_invite_tone, edit_invite_text, change_date, change_venue, adjust_budget, add_invitees, remove_invitees, unknown]. "
    "Optional keys by type: spouse_name, event_date(YYYY-MM-DD), budget(int), venue(string), style(one of playful,formal,romantic,friendly,professional), brevity(one of short,medium,detailed), template(string), emails(array)."
)


def build_interpret_nl_prompt(utterance: str) -> str:
    return f"{NL_SCHEMA}\n\nInstruction: {utterance}\n\nJSON:"


def parse_interpret_nl(text: str, utterance: str) -> Dict[str, Any]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
    except Exception:
        pass
    return {"type": "unknown", "utterance": utterance}


def interpret_nl(utterance: str) -> Dict[str, Any]:
    """Map a natural instruction to a structured action dict with fields:
    {"type": <intent>, ...}. No chain-of-thought is produced or logged.
    If server LLM is disabled, uses rules and returns unknown when ambiguous.
    """
    utter = utterance.strip()
    low = utter.lower()

    # Quick rules for common intents
    if any(k in low for k in ["start", "plan", "birthday"]):
        action: Dict[str, Any] = {"type": "start_birthday_plan"}
        m = re.search(r"for\s+([A-Za-z ]+)", utter)
        if m:
            name = m.group(1).strip().strip('.')
            action["spouse_name"] = name
        m = re.search(r"budget\s+(\d+[kK]?)", low)
        if m:
            val = m.group(1)
            action["budget"] = int(val[:-1]) * 1000 if val.lower().endswith('k') else int(val)
        return action

    if any(k in low for k in ["tone", "playful", "formal", "romantic", "friendly", "professional"]):
        m_style = re.search(r"(playful|formal|romantic|friendly|professional)", low)
        style = m_style.group(1) if m_style else "friendly"
        m_brev = re.search(r"(short|brief|detailed|long|medium)", low)
        x = m_brev.group(1) if m_brev else "medium"
        brev = "short" if x in ("short", "brief") else ("detailed" if x in ("detailed", "long") else "medium")
        return {"type": "edit_invite_tone", "style": style, "brevity": brev, "notes": utter}

    if any(k in low for k in ["template", "rewrite", "edit invite", "change invite", "reword"]):
        return {"type": "edit_invite_text", "template": utter}

    if "budget" in low:
        m = re.search(r"(\d+[kK]?)", low)
        if m:
            val = m.group(1)
            amount = int(val[:-1]) * 1000 if val.lower().endswith('k') else int(val)
            return {"type": "adjust_budget", "budget": amount}

    if "date" in low:
        m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
        if m:
            return {"type": "change_date", "event_date": m.group(1)}

    if "venue" in low or "place" in low:
        m = re.search(r"(at|to)\s+([A-Za-z0-9 &'\-]+)$", utter)
        if m:
            return {"type": "change_venue", "venue": m.group(2).strip()}

    if "add" in low and "invite" in low:
        emails = re.findall(r"[\w.]+@[\w.-]+", utter)
        if emails:
            return {"type": "add_invitees", "emails": emails}

    if "remove" in low and "invite" in low:
        emails = re.findall(r"[\w.]+@[\w.-]+", utter)
        if emails:
            return {"type": "remove_invitees", "emails": emails}

    # LLM fallback for richer parsing
    llm = get_llm()
    if llm is None:
        return {"type": "unknown", "utterance": utter}

    prompt = build_interpret_nl_prompt(utter)
    try:
        resp = llm.invoke(prompt)
        txt = _safe_text(resp)
        return parse_interpret_nl(txt, utter)
    except Exception:
        return {"type": "unknown", "utterance": utter}
