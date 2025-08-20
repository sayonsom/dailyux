from datetime import datetime
from typing import List, Dict, Any, Optional
from app.schemas import AgentCard

DateLike = str


def _parse_event_date(date_str: DateLike, current_year: int) -> Optional[datetime]:
    try:
        if len(date_str) == 10:  # YYYY-MM-DD
            return datetime.fromisoformat(date_str)
        # MM-DD -> attach current year
        return datetime.fromisoformat(f"{current_year}-{date_str}")
    except Exception:
        return None


def _upcoming_within(days_ahead: int, today: datetime, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in items:
        dstr = it.get("date")
        if not dstr:
            continue
        dt = _parse_event_date(dstr, today.year)
        if not dt:
            continue
        delta = (dt.date() - today.date()).days
        if 0 <= delta <= days_ahead:
            it2 = dict(it)
            it2["days_left"] = delta
            out.append(it2)
    out.sort(key=lambda x: x.get("days_left", 999))
    return out


def run(profile, req):
    ctx = req.get("context", {})
    date = req.get("date")
    today = datetime.fromisoformat(date) if date else datetime.now()

    fam = profile.get("meta", {}).get("family", [])
    col = profile.get("meta", {}).get("colleagues", [])

    fam_events: List[Dict[str, Any]] = []
    for f in fam:
        name = f.get("name")
        if f.get("birthday"):
            fam_events.append({"name": name, "relation": f.get("relation", "family"), "type": "birthday", "date": f["birthday"]})
        if f.get("anniversary"):
            fam_events.append({"name": name, "relation": f.get("relation", "family"), "type": "anniversary", "date": f["anniversary"]})

    col_events: List[Dict[str, Any]] = []
    for c in col:
        name = c.get("name")
        if c.get("birthday"):
            col_events.append({"name": name, "relation": c.get("role", "colleague"), "type": "birthday", "date": c["birthday"]})

    upcoming_fam = _upcoming_within(14, today, fam_events)
    upcoming_col = _upcoming_within(14, today, col_events)
    total = len(upcoming_fam) + len(upcoming_col)

    if total == 0:
        return AgentCard(
            agent="CelebrationsAgent",
            title="Celebrations",
            summary="No family/colleague events in next 2 weeks.",
            priority=7,
            data={"upcoming_family": [], "upcoming_colleagues": []},
        )

    first = (upcoming_fam + upcoming_col)[0]
    who = f"{first['name']} ({first['type']}) in {first['days_left']}d"
    return AgentCard(
        agent="CelebrationsAgent",
        title="Upcoming Celebrations",
        summary=f"{total} upcoming; next: {who}",
        priority=2,
        data={"upcoming_family": upcoming_fam, "upcoming_colleagues": upcoming_col},
    )
