from app.schemas import AgentCard

def run(profile, req):
    meta = profile.get("meta", {})
    ctx = req.get("context", {})
    night = bool(meta.get("night_owl") or ctx.get("night_owl"))

    # Pick a free block if available
    fb = ctx.get("free_blocks", [])
    slot = None
    if fb:
        # prefer a 30–45m block in morning/late afternoon
        for b in fb:
            if b["start"] <= "09:30" or ("16:00" <= b["start"] <= "18:30"):
                slot = b; break
        slot = slot or fb[0]

    plan = "Evening bike 45m + core" if night else "AM walk 30m + PM bodyweight 20m"
    when = f" at {slot['start']}" if slot else ""

    return AgentCard(agent="FitnessAgent", title="Today's Workout", summary=plan + when, priority=4, data={"plan": plan, "suggested_time": slot, "meal_tip": "Protein lunch; hydrate 2L"})
