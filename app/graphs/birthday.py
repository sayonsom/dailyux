from datetime import datetime, timedelta
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any, List
from app.tools.calendar import calendar_lookup
from app.tools.comms import compose_message, send_invites

BirthdayState = Dict[str, Any]


def _suggest_themes(profile: Dict[str, Any], honoree_likes: List[str]) -> List[str]:
    likes = [l.lower() for l in (honoree_likes or [])]
    out = []
    if any(x in likes for x in ["classical", "indian art", "ballet"]):
        out.append("Elegant Minimal")
    if any(x in likes for x in ["football", "f1", "ps5"]):
        out.append("Sporty Fun")
    if profile.get("meta", {}).get("parties"):
        out.append("Lively Social")
    if profile.get("meta", {}).get("stressors"):
        out.append("Calm & Cozy")
    if not out:
        out = ["Warm & Minimal", "Modern Chic", "Cozy Home"]
    return list(dict.fromkeys(out))[:3]


def _suggest_venues(profile: Dict[str, Any]) -> Dict[str, List[str]]:
    city = profile.get("meta", {}).get("city", "your area")
    # Stubbed suggestions; in production, integrate an API
    restaurants = [
        f"{city} Bistro",
        f"The Blue Door ({city})",
        f"Rooftop Garden ({city})",
    ]
    home_styles = ["Home - Backyard dinner", "Home - Living room tapas", "Home - Terrace soiree"]
    return {"restaurants": restaurants, "home": home_styles}


def _suggest_times(availability: List[Dict[str, Any]]) -> List[str]:
    # Pick up to 3 options, prefer 18:30-21:30 windows
    opts: List[str] = []
    for e in availability:
        t = e.get("time") or e.get("start")
        if not t:
            continue
        if "18:00" <= t <= "21:00":
            opts.append(t)
    # Fallbacks: first two times in availability
    if not opts:
        for e in availability[:3]:
            t = e.get("time") or e.get("start")
            if t:
                opts.append(t)
    # Ensure uniqueness, limit 3
    seen, uniq = set(), []
    for t in opts:
        if t not in seen:
            seen.add(t); uniq.append(t)
    return uniq[:3]


def _invitee_suggestions(profile: Dict[str, Any]) -> List[str]:
    emails: List[str] = []
    for f in profile.get("meta", {}).get("family", []) or []:
        if f.get("email"):
            emails.append(f["email"])
    for c in profile.get("meta", {}).get("colleagues", []) or []:
        if c.get("email"):
            emails.append(c["email"])
    # Unique and cap
    seen, out = set(), []
    for e in emails:
        if e not in seen:
            seen.add(e); out.append(e)
    return out[:10]


def node_calendar(state: BirthdayState):
    params = state.get("params", {})
    date = params.get("event_date") or (datetime.now().date() + timedelta(days=14)).isoformat()
    cal = calendar_lookup(state.get("profile", {}), date)
    plan = dict(state.get("plan", {}))
    plan["date"] = date
    plan["availability"] = (cal.get("events", [])[:5])
    # Propagate honoree context if provided
    if params.get("relation"):
        plan["relation"] = params.get("relation")
    if params.get("event_type"):
        plan["event_type"] = params.get("event_type")
    if params.get("spouse_name"):
        plan["honoree_name"] = params.get("spouse_name")
    # Time suggestions based on availability
    plan.setdefault("time_options", _suggest_times(plan.get("availability", [])))
    new_state = dict(state); new_state["plan"] = plan
    return new_state


def node_plan_event(state: BirthdayState):
    p = state.get("params", {})
    prof = state.get("profile", {})
    spouse = p.get("spouse_name", state.get("plan", {}).get("honoree_name") or "Spouse")
    budget = p.get("budget", 10000)
    relation = state.get("plan", {}).get("relation") or p.get("relation") or "family"
    event_type = state.get("plan", {}).get("event_type") or p.get("event_type") or "birthday"
    venue_default = "Home" if prof.get("meta", {}).get("prefers_home") else "Trendy lounge"
    # Theme/venue candidates from profile + honoree likes
    honoree_likes = []
    for m in prof.get("meta", {}).get("family", []) or []:
        if m.get("name") == spouse and isinstance(m.get("likes"), list):
            honoree_likes = m["likes"]; break
    theme_options = _suggest_themes(prof, honoree_likes)
    venue_options = _suggest_venues(prof)

    plan = dict(state.get("plan", {}))
    plan.update({
        "spouse_name": spouse,
        "honoree_name": plan.get("honoree_name") or spouse,
        "relation": relation,
        "event_type": event_type,
        "venue": plan.get("venue") or venue_default,
        "theme": plan.get("theme") or (theme_options[0] if theme_options else "Warm & Minimal"),
        "theme_options": theme_options,
        "venue_options": venue_options,
        "budget": budget,
        "timeline": ["18:30 arrivals","19:15 toast","20:00 dinner","21:00 cake"],
        "stage": plan.get("stage") or "review_theme_venue",
        "next_actions": ["change_theme","change_venue","confirm_theme_venue"],
    })
    new_state = dict(state); new_state["plan"] = plan
    return new_state


def node_compose_invites(state: BirthdayState):
    plan = dict(state.get("plan", {}))
    # Gate 1: require theme/venue confirmation
    if plan.get("stage") == "review_theme_venue":
        # Ensure time options exist
        plan.setdefault("time_options", _suggest_times(plan.get("availability", [])))
        new_state = dict(state); new_state["plan"] = plan
        return new_state

    # Gate 2: time selection
    if not plan.get("time"):
        plan["stage"] = "pick_time"
        plan["next_actions"] = ["choose_time","propose_more_times","change_date"]
        plan.setdefault("time_options", _suggest_times(plan.get("availability", [])))
        new_state = dict(state); new_state["plan"] = plan
        return new_state

    # Gate 3: invitee selection
    if not plan.get("invitees"):
        plan["stage"] = "select_invitees"
        plan["invitee_suggestions"] = plan.get("invitee_suggestions") or _invitee_suggestions(state.get("profile", {}))
        plan["next_actions"] = ["add_invitees","remove_invitees","confirm_invitees"]
        new_state = dict(state); new_state["plan"] = plan
        return new_state

    # Compose invite template, move to review
    honoree = plan.get("honoree_name") or plan.get("spouse_name", "Spouse")
    tmpl = plan.get("invite_message_template") or (
        "Hi {name},\nYou're invited to {spouse}'s surprise on {date} at {venue} {time}. RSVP: {rsvp}"
    )
    # Provide preview for first invitee (client can render)
    sample = (plan.get("invitees") or ["Guest"])[0]
    preview = tmpl.replace("{name}", sample)
    plan.update({
        "invite_message_template": tmpl,
        "invite_preview": preview,
        "next_actions": ["edit_invite_tone","edit_invite_text","confirm_send"],
        "stage": "review_invite",
    })
    new_state = dict(state); new_state["plan"] = plan
    return new_state


def node_send_invites(state: BirthdayState):
    plan = dict(state.get("plan", {}))
    if plan.get("stage") != "ready_to_send":
        # Not authorized to send yet
        new_state = dict(state); new_state["plan"] = plan
        return new_state
    invitees = plan.get("invitees", [])
    msg = (plan.get("invite_message_template") or "").replace("{name}", "Friend").format(
        spouse=plan.get("spouse_name","Spouse"), date=plan.get("date",""), venue=plan.get("venue",""), time=plan.get("time",""), rsvp="https://example.com/rsvp"
    )
    result = send_invites(invitees, msg)
    plan["invite_result"] = result
    plan["stage"] = "sent"
    new_state = dict(state); new_state["plan"] = plan
    return new_state


def build_birthday_graph():
    g = StateGraph(dict)
    g.add_node("calendar", node_calendar)
    g.add_node("planner", node_plan_event)
    g.add_node("compose", node_compose_invites)
    g.add_node("send", node_send_invites)
    g.add_edge(START, "calendar"); g.add_edge("calendar","planner"); g.add_edge("planner","compose"); g.add_edge("compose","send"); g.add_edge("send", END)
    return g.compile(checkpointer=MemorySaver())

BIRTHDAY_GRAPH = build_birthday_graph()
