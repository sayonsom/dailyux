from app.schemas import AgentCard


def run(profile, req):
    ctx = req.get("context", {})
    fb = ctx.get("free_blocks", [])

    # Choose lunch slot around midday if available, else earliest block
    slot = None
    for b in fb:
        if "11:30" <= b.get("start", "00:00") <= "14:30":
            slot = b; break
    slot = slot or (fb[0] if fb else None)

    load = ctx.get("day_load", "medium")
    plan = {
        "breakfast": "Oats + nuts + fruit; coffee/tea",
        "lunch": "Protein-forward bowl; greens; skip sugary drinks",
        "snack": "Greek yogurt or nuts",
        "dinner": "Light carbs + lean protein; early if possible",
        "hydration": "Target 2–2.5L water",
    }
    if load == "heavy":
        plan["snack"] = "Banana + peanut butter (energy)"

    summary = "Balanced meals; hydrate 2–2.5L" + (f"; lunch at {slot['start']}" if slot else "")
    return AgentCard(
        agent="NutritionAgent",
        title="Nutrition Plan",
        summary=summary,
        priority=5,
        data={"plan": plan, "suggested_time": slot},
    )
