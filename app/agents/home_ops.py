from typing import Dict, Any
from app.schemas import AgentCard

_DEF_TITLES = {
    "decide_menu": "Decide Menu",
    "grocery_shopping": "Grocery Shopping",
    "wifi_access": "Guest Wi‑Fi Access",
    "secure_locks": "Secure Home Locks",
    "post_cleanup": "Post-Party Cleanup",
}


def _summary_from_result(kind: str, result: Dict[str, Any]) -> str:
    if kind == "decide_menu":
        return f"Menu for {result.get('guests', '?')} guests ({result.get('veg','?')} veg). Dishes: {', '.join(result.get('dishes', []))}"
    if kind == "grocery_shopping":
        items = result.get("list", [])
        return f"{len(items)} items ordered. ETA {result.get('eta','')}."
    if kind == "wifi_access":
        return f"SSID {result.get('ssid','Guest')} ready; QR generated."
    if kind == "secure_locks":
        return "All smart locks engaged."
    if kind == "post_cleanup":
        rooms = ", ".join(result.get("rooms", []))
        return f"Robot vacuum ran; cleaned: {rooms}."
    return "Task completed."


def run(profile: Dict[str, Any], req: Dict[str, Any]) -> AgentCard:
    kind = req.get("kind", "home_ops")
    result = req.get("result", {})
    title = _DEF_TITLES.get(kind, "Home Ops")
    summary = _summary_from_result(kind, result)
    return AgentCard(
        agent="HomeOpsAgent",
        title=title,
        summary=summary,
        priority=3,
        data={"kind": kind, "result": result},
    )
