from app.schemas import AgentCard


def run(profile, req):
    meta = profile.get("meta", {})
    hobby = meta.get("hobby")
    ctx = req.get("context", {})
    is_weekend = bool(ctx.get("is_weekend"))

    # Weekend vs weekday tasks
    if is_weekend:
        task = "Explore hobby for 45m: unstructured, fun session"
        if hobby == "garden_automation":
            task = "Garden project: set up moisture sensors; prune basil (45m)"
        elif hobby == "guitar":
            task = "Learn a new riff + jam with backing track (45m)"
        priority = 5
    else:
        task = "15m reading/journaling"
        if hobby == "garden_automation":
            task = "Check soil moisture; test drip; trim basil (15m)"
        elif hobby == "guitar":
            task = "Practice chord transitions + metronome (15m)"
        priority = 7

    # Slot selection respects weekend/weekday
    slot = None
    for b in ctx.get("free_blocks", []):
        if is_weekend:
            # prefer late morning/afternoon on weekends
            if "10:30" <= b["start"] <= "17:30":
                slot = b; break
        else:
            if "12:00" <= b["start"] <= "18:00":
                slot = b; break
    # fallback
    if not slot and ctx.get("free_blocks"):
        slot = ctx["free_blocks"][0]

    summary = task + (f" at {slot['start']}" if slot else "")
    return AgentCard(agent="HobbyAgent", title="Hobby Nudge", summary=summary, priority=priority, data={"task": task, "suggested_time": slot})
