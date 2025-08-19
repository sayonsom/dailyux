from typing import List, Dict, Any
import re
from app.llm.llm import get_llm

class _SafeDict(dict):
    def __missing__(self, key):
        # Leave unknown placeholders intact
        return "{" + key + "}"

def compose_message(template: str, params: Dict[str, str]) -> str:
    """Safely fill placeholders; unknown keys remain as-is."""
    try:
        return template.format_map(_SafeDict(params))
    except Exception:
        # Conservative fallback
        msg = template
        for k, v in params.items():
            msg = msg.replace("{" + k + "}", v)
        return msg

def send_invites(invitees: List[str], message: str) -> Dict[str, any]:
    return {"sent": len(invitees), "failed": [], "preview": message[:180]}

def render_invite_preview(template: str, invitees: List[str], params: Dict[str, str]) -> str:
    sample = invitees[0] if invitees else "Guest"
    local = dict(params)
    # Support either {guest} or {name} placeholder
    if "{guest}" in template:
        local.setdefault("guest", sample)
    else:
        local.setdefault("name", sample)
    return compose_message(template, local)[:180]

def _safe_content(resp: Any) -> str:
    try:
        text = getattr(resp, "content", None)
        return text if isinstance(text, str) else (str(resp) if resp is not None else "")
    except Exception:
        return ""

def rewrite_invite_template(style: str, brevity: str, current_template: str, constraints: Dict[str, str]) -> str:
    """Rewrite invite template with tone/brevity; preserve placeholders like {name},{guest},{spouse},{date},{venue},{rsvp}."""
    llm = get_llm()
    if llm is None:
        # Simple deterministic tweaks
        t = current_template.strip()
        if brevity == "short":
            t = re.sub(r"\s*\n\s*", " ", t)
            # Keep first sentence if present
            m = re.match(r"(.+?[.!?])\s", t)
            if m:
                t = m.group(1)
        if style == "playful":
            t = ("🎉 " + t.replace("You are invited", "You're invited").replace("You are", "You're") + " 🎂").strip()
        elif style == "formal":
            t = t.replace("Hi", "Dear").replace("Hey", "Dear").replace("You're", "You are")
        elif style == "romantic":
            t = ("❤️ " + t + " ❤️").strip()
        elif style == "friendly":
            t = t
        elif style == "professional":
            t = t
        return t

    system = (
        "You revise an event invite template. Keep placeholders EXACTLY unchanged: "
        "{name}, {guest}, {spouse}, {date}, {venue}, {rsvp}. Apply the requested tone and brevity. "
        "Return ONLY the revised template text, no code fences, no commentary."
    )
    prompt = (
        f"{system}\n\nTONE: {style}\nBREVITY: {brevity}\n\nCurrent Template:\n{current_template}\n\nRevised Template:"
    )
    # Note: Avoid system role; model uses human messages
    resp = llm.invoke(prompt)
    text = _safe_content(resp).strip()
    # Trim accidental fences
    if text.startswith("```"):
        lines = [l for l in text.splitlines() if l.strip()]
        # Drop first and last if they are code fences
        if lines and lines[0].startswith("````"):
            lines = lines[1:]
        if lines and lines[-1].startswith("````"):
            lines = lines[:-1]
        text = "\n".join(lines).strip("`\n ")
    return text or current_template
