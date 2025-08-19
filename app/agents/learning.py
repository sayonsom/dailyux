from app.schemas import AgentCard

COURSE_SUGGESTIONS = {
    "Executive": [
        "Strategic Thinking: 3 short case videos",
        "AI for Managers: 30m primer",
    ],
    "C-level": [
        "Board Communication Masterclass: 1 module",
        "Finance for Non-CFOs: Working capital deep dive",
    ],
    "GenZ": [
        "JavaScript projects: Build a small game",
        "Design basics: 3 mini lessons",
    ],
}


def run(profile, req):
    role = (profile.get("meta", {}).get("role") or "").title()
    ctx = req.get("context", {})

    picks = COURSE_SUGGESTIONS.get(role, ["Learn something new: 30m", "TED/YouTube: 2 high-signal talks"])

    # Find a 25–45m block earlier in the day
    slot = None
    for b in ctx.get("free_blocks", []):
        if b.get("minutes", 0) >= 25 and b.get("start", "00:00") <= "12:30":
            slot = b; break
    slot = slot or (ctx.get("free_blocks", [None])[0])

    return AgentCard(
        agent="LearningAgent",
        title="Learning Sprint",
        summary=(picks[0] if picks else "Learning block") + (f" at {slot['start']}" if slot else ""),
        priority=6,
        data={"suggestions": picks, "suggested_time": slot},
    )
