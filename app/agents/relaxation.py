from app.schemas import AgentCard


def run(profile, req):
    meta = profile.get("meta", {})
    ctx = req.get("context", {})
    night = bool(meta.get("night_owl") or ctx.get("night_owl"))
    is_weekend = bool(ctx.get("is_weekend"))

    routine = ["4-7-8 breathing (5 cycles)", "Screen off 30m before bed"]
    if meta.get("religious"):
        routine.insert(0, "Prayer + gratitude (5m)")
    if is_weekend:
        routine.append("Reflect on highlights of the week")
    lights_out = "23:30" if night else ("23:00" if is_weekend else "22:30")

    return AgentCard(
        agent="RelaxationAgent",
        title="Wind Down" if not is_weekend else "Weekend Wind Down",
        summary=f"{' · '.join(routine)}; lights out {lights_out}",
        priority=8 if not is_weekend else 6,
        data={"journal_prompts": ["What gave me energy today?", "What can I let go of?"], "lights_out": lights_out, "routine": routine, "weekend": is_weekend},
    )
