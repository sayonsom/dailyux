from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any, List, Tuple
from datetime import datetime
from app.schemas import AgentCard
from app.agents import getting_started, traffic, work_life, fitness, hobby, life_after_work, relaxation
# New agents
from app.agents import nutrition, finance_errands, learning, celebrations
from app.tools.calendar import calendar_lookup
from app.llm.llm import generate_bullets

PlannerState = Dict[str, Any]

# ---------------- Context + Routing ----------------

def _parse_time(t: str) -> Tuple[int, int]:
    try:
        h, m = t.split(":"); return int(h), int(m)
    except Exception:
        return 0, 0


def _to_minutes(t: str) -> int:
    h, m = _parse_time(t); return h * 60 + m


def _fmt_range(a: str, b: str) -> str:
    return f"{a}-{b}"


def compute_day_context(profile: Dict[str, Any], date: str) -> Dict[str, Any]:
    """Derive useful planning features from the profile calendar and meta."""
    cal = calendar_lookup(profile, date)
    events = sorted(cal.get("events", []), key=lambda e: e.get("time", "23:59"))
    count = len(events)
    first_time = events[0]["time"] if events else None
    last_time = events[-1]["time"] if events else None

    # Free blocks between events (simple):
    free_blocks: List[Dict[str, Any]] = []
    prev = None
    for e in events:
        if prev is None:
            # morning free time before first event
            if e["time"] > "08:00":
                start, end = "06:00", e["time"]
                free_blocks.append({"start": start, "end": end, "minutes": max(0, _to_minutes(end) - _to_minutes(start))})
        else:
            start, end = prev["time"], e["time"]
            free_blocks.append({"start": start, "end": end, "minutes": max(0, _to_minutes(end) - _to_minutes(start))})
        prev = e
    if last_time and last_time < "20:30":
        start, end = last_time, "22:30"
        free_blocks.append({"start": start, "end": end, "minutes": max(0, _to_minutes(end) - _to_minutes(start))})

    # Simple load score
    load = "light" if count <= 2 else ("medium" if count <= 4 else "heavy")

    # Event type hints
    type_counts: Dict[str, int] = {"meeting": 0, "call": 0, "family": 0, "party": 0, "travel": 0}
    for e in events:
        title = (e.get("title") or "").lower()
        if "meeting" in title or "review" in title: type_counts["meeting"] += 1
        if "call" in title or "sync" in title: type_counts["call"] += 1
        if "family" in title or "kids" in title: type_counts["family"] += 1
        if "party" in title or "drink" in title: type_counts["party"] += 1
        if "flight" in title or "commute" in title or "drive" in title: type_counts["travel"] += 1

    # Focus windows: longest morning/afternoon blocks >= 45m
    long_blocks = [b for b in free_blocks if b.get("minutes", 0) >= 45]
    morning = [b for b in long_blocks if b["start"] <= "12:00"]
    afternoon = [b for b in long_blocks if "12:00" < b["start"] <= "18:30"]
    morning.sort(key=lambda b: b["minutes"], reverse=True)
    afternoon.sort(key=lambda b: b["minutes"], reverse=True)
    focus_windows = []
    if morning: focus_windows.append({"window": _fmt_range(morning[0]["start"], morning[0]["end"]), "minutes": morning[0]["minutes"]})
    if afternoon: focus_windows.append({"window": _fmt_range(afternoon[0]["start"], afternoon[0]["end"]), "minutes": afternoon[0]["minutes"]})

    # Calendar span + density
    span_min = max(1, (_to_minutes(last_time) - _to_minutes(first_time))) if first_time and last_time else 480
    density = round((count / (span_min / 60.0)), 2) if span_min else 0.0

    # Date features
    try:
        weekday = datetime.fromisoformat(date).strftime("%a")
        is_weekend = weekday in ("Sat", "Sun")
    except Exception:
        weekday, is_weekend = "", False

    meta = profile.get("meta", {})
    context = {
        "events": events,
        "event_count": count,
        "first_event_time": first_time,
        "last_event_time": last_time,
        "first_event_title": (events[0].get("title") if events else None),
        "last_event_title": (events[-1].get("title") if events else None),
        "free_blocks": free_blocks,
        "block_count": len(free_blocks),
        "longest_block": max([b.get("minutes", 0) for b in free_blocks] or [0]),
        "focus_windows": focus_windows,
        "day_load": load,
        "meeting_density": density,
        "night_owl": bool(meta.get("night_owl")),
        "role": meta.get("role"),
        "prefers_parties": bool(meta.get("parties")),
        "religious": bool(meta.get("religious")),
        "music": meta.get("music"),
        "hobby": meta.get("hobby"),
        "weekday": weekday,
        "is_weekend": is_weekend,
        "event_types": type_counts,
    }
    return context


def router_order(profile: Dict[str, Any], ctx: Dict[str, Any]) -> List[str]:
    """Decide which agents to run and in what order based on profile type and day context."""
    role = (ctx.get("role") or profile.get("meta", {}).get("role", "")).lower()
    night = bool(ctx.get("night_owl"))
    load = ctx.get("day_load", "medium")
    is_weekend = bool(ctx.get("is_weekend"))

    base = ["getting_started", "celebrations"]  # celebrations early if any upcoming

    # Include new agents by default in sensible positions
    if "exec" in role or "c-level" in role or "c level" in role:
        seq = base + [
            "work_life", "traffic", "nutrition", "learning", "fitness", "finance_errands", "hobby", "life_after_work", "relaxation"
        ]
    elif "genz" in role or "gen z" in role:
        seq = base + (["hobby"] if night else []) + [
            "traffic", "work_life", "nutrition", "learning", "fitness", "finance_errands", "life_after_work", "relaxation"
        ]
    else:
        seq = base + (["traffic", "work_life"] if not night else ["work_life", "traffic"]) + [
            "nutrition", "learning", "hobby", "life_after_work", "fitness", "finance_errands", "relaxation"
        ]

    # If weekend, bring leisure/errands earlier; downshift work
    if is_weekend:
        for name in ["hobby", "learning", "finance_errands", "life_after_work"]:
            if name in seq:
                seq.remove(name); seq.insert(2, name)
        # push work_life later
        if "work_life" in seq:
            seq.remove("work_life"); seq.insert(len(seq)-1, "work_life")
        # traffic later on weekends
        if "traffic" in seq:
            seq.remove("traffic"); seq.insert(len(seq)-2, "traffic")

    # If light load, move fitness earlier; if heavy, delay hobby
    if load == "light" and "fitness" in seq:
        seq.remove("fitness"); seq.insert(2 if not night else 3, "fitness")
    if load == "heavy" and "hobby" in seq:
        seq.remove("hobby"); seq.insert(len(seq)-1, "hobby")

    # Dynamic shift of LifeAfterWork based on meeting density and evening plans
    density = float(ctx.get("meeting_density") or 0.0)
    last_time = ctx.get("last_event_time") or ""
    event_types = ctx.get("event_types") or {}
    evening_engagement = bool((last_time >= "19:00") or (event_types.get("party", 0) + event_types.get("family", 0) > 0))

    if "life_after_work" in seq:
        seq.remove("life_after_work")
        if evening_engagement:
            try:
                idx = seq.index("learning") + 1
            except ValueError:
                idx = 3
            seq.insert(min(idx, len(seq)-1), "life_after_work")
        elif density >= 1.0 or load == "heavy":
            seq.insert(len(seq)-1, "life_after_work")
        else:
            seq.insert(len(seq)-1, "life_after_work")

    # Ensure uniqueness and valid names
    seen, out = set(), []
    for s in seq:
        if s in seen or s not in NODE_FUN: continue
        seen.add(s); out.append(s)
    return out


# ---------------- Node wrappers ----------------

def node_getting_started(state: PlannerState):
    card = getting_started.run(state["profile"], state.get("request", {})); state.setdefault("outputs", {}).setdefault("cards", []).append(card.dict()); return state

def node_traffic(state: PlannerState):
    card = traffic.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_work_life(state: PlannerState):
    card = work_life.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_fitness(state: PlannerState):
    card = fitness.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_hobby(state: PlannerState):
    card = hobby.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_life_after_work(state: PlannerState):
    card = life_after_work.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_relaxation(state: PlannerState):
    card = relaxation.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

# New node wrappers

def node_nutrition(state: PlannerState):
    card = nutrition.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_finance_errands(state: PlannerState):
    card = finance_errands.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_learning(state: PlannerState):
    card = learning.run(state["profile"], state.get("request", {})); state["outputs"]["cards"].append(card.dict()); return state

def node_celebrations(state: PlannerState):
    card = celebrations.run(state["profile"], state.get("request", {}))
    if card:
        state["outputs"]["cards"].append(card.dict())
    return state

# Supervisor insights card

def supervisor_insights(profile: Dict[str, Any], ctx: Dict[str, Any]) -> AgentCard:
    role = (ctx.get("role") or "").title(); load = ctx.get("day_load", "medium")
    fw = ctx.get("focus_windows") or []
    fw_str = ", ".join([w["window"] for w in fw]) if fw else ""
    summary = f"Load {load}; {ctx.get('event_count',0)} events" + (f"; focus {fw_str}" if fw_str else "")

    prompt = (
        "You are a pragmatic day planner. Given user role, day load, "
        "free blocks and first/last events, produce 3 crisp planning tips. "
        "Prioritize focus protection, timeboxing, and energy management."
        f"\nRole: {role}\nLoad: {load}\nFirst: {ctx.get('first_event_time')} {ctx.get('first_event_title')}"
        f"\nLast: {ctx.get('last_event_time')} {ctx.get('last_event_title')}"
        f"\nFocus windows: {fw_str}\nNight owl: {bool(ctx.get('night_owl'))}\n"
    )
    bullets = generate_bullets(prompt, count=3) or [
        (f"Protect 60m deep work {fw[0]['window']}" if fw else "Protect one 60m deep-work block"),
        "Batch emails twice; avoid constant context switching",
        ("Prep for evening unwind by 21:30" if not bool(ctx.get('night_owl')) else "Aim lights out by 23:30"),
    ]
    return AgentCard(agent="SupervisorAgent", title="Planner Insights", summary=summary, priority=0, data={"insights": bullets, "focus_windows": fw, "load": load, "role": role})

# Fallback linear variants so all edges exist
LINEAR_A = ["getting_started","celebrations","traffic","work_life","nutrition","learning","fitness","finance_errands","hobby","life_after_work","relaxation"]
LINEAR_B = ["getting_started","celebrations","work_life","traffic","nutrition","learning","hobby","life_after_work","fitness","finance_errands","relaxation"]

NODE_FUN = {
    "getting_started": node_getting_started,
    "traffic": node_traffic,
    "work_life": node_work_life,
    "fitness": node_fitness,
    "hobby": node_hobby,
    "life_after_work": node_life_after_work,
    "relaxation": node_relaxation,
    # New
    "nutrition": node_nutrition,
    "finance_errands": node_finance_errands,
    "learning": node_learning,
    "celebrations": node_celebrations,
}

# ---------------- Legacy graph (kept for compatibility) ----------------

def build_supervisor_graph():
    g = StateGraph(dict)
    for name in NODE_FUN: g.add_node(name, NODE_FUN[name])
    def entry(state: PlannerState): return state
    g.add_node("entry", entry)

    def bind_linear(seq: List[str]):
        for i in range(len(seq)-1): g.add_edge(seq[i], seq[i+1])
        g.add_edge(seq[-1], END)

    g.add_edge(START, "entry")
    # Connect entry to both possible starts; actual REST/WS path does explicit routing
    g.add_edge("entry", "getting_started")
    bind_linear(LINEAR_A); bind_linear(LINEAR_B)
    return g.compile(checkpointer=MemorySaver())

SUPERVISOR_GRAPH = build_supervisor_graph()
