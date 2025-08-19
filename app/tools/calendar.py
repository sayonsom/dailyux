from typing import Dict, Any

def calendar_lookup(profile: Dict[str, Any], date: str) -> Dict[str, Any]:
    day_key = next(iter(profile.get("days", {"Day_1": {}})))
    blocks = profile.get("days", {}).get(day_key, {})
    items = [{"time": t, "title": v} for t, v in sorted(blocks.items())]
    return {"events": items}
