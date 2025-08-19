from app.schemas import AgentCard
from app.tools.calendar import calendar_lookup
from app.tools.envs import weather
from app.tools.content import spotify_recs

def run(profile, req):
    date = req.get("date")
    ctx = (req.get("context") or {})
    is_weekend = bool(ctx.get("is_weekend"))
    cal = calendar_lookup(profile, date)
    wx = weather("Bengaluru", date)
    taste = profile.get("meta", {}).get("music", "chill")
    recs = spotify_recs("focus" if not is_weekend else "relax", taste)

    first_ev = ctx.get("events", [{}])[0] if ctx.get("events") else None
    first_str = f"Next: {first_ev.get('time')} {first_ev.get('title')}" if first_ev else ("Slow morning" if is_weekend else "Open morning")

    load = ctx.get("day_load", "medium")
    if is_weekend:
        focus_tip = "Keep it light; one meaningful personal task"
    else:
        focus_tip = {
            "light": "Batch emails first, then deep work 90m",
            "medium": "Timebox meetings; protect a 60m deep-work block",
            "heavy": "Triage quickly; pick one high-impact task",
        }.get(load, "Protect one focused block")

    summary = f"{len(cal['events'])} events. Weather {wx['condition']} {wx['low']}–{wx['high']}°C. {first_str}."
    data = {
        "calendar": cal,
        "weather": wx,
        "music": recs[:2],
        "focus_tip": focus_tip,
        "free_blocks": ctx.get("free_blocks", []),
        "weekend": is_weekend,
    }
    return AgentCard(
        agent="GettingStartedAgent",
        title="Weekend Brief" if is_weekend else "Morning Brief",
        summary=summary,
        priority=1,
        data=data,
    )
