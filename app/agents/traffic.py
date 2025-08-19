from app.schemas import AgentCard
from app.tools.envs import route

def run(profile, req):
    ctx = req.get("context", {})
    origin = req.get("origin", "Home"); dest = req.get("dest", "Office"); when = req.get("date")
    # If first event is a meeting at office, recommend commute path
    first = (ctx.get("events") or [{}])[0]
    if first:
        title = (first or {}).get("title", "").lower()
        if "meeting" in title or "office" in title:
            dest = "Office"
    r = route(origin, dest, when)
    leave_by = None
    if ctx.get("first_event_time") and r.get("eta_min"):
        # naive: arrive 10m before event
        hh, mm = map(int, ctx["first_event_time"].split(":"))
        total = hh*60 + mm - int(r["eta_min"]) - 10
        leave_by = f"{total//60:02d}:{total%60:02d}"
    summary = f"ETA {r['eta_min']} min via {', '.join(r['route'])}" + (f"; leave by {leave_by}" if leave_by else "")
    return AgentCard(agent="TrafficAgent", title="Best Route", summary=summary, priority=2, data={**r, "leave_by": leave_by})
