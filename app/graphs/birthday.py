from datetime import datetime, timedelta
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from typing import Dict, Any
from app.tools.calendar import calendar_lookup
from app.tools.comms import compose_message, send_invites

BirthdayState = Dict[str, Any]

def node_calendar(state: BirthdayState):
    params = state.get("params", {})
    date = params.get("event_date") or (datetime.now().date() + timedelta(days=14)).isoformat()
    cal = calendar_lookup(state.get("profile", {}), date)
    plan = dict(state.get("plan", {}))
    plan["date"] = date
    plan["availability"] = (cal.get("events", [])[:2])
    # Propagate honoree context if provided
    if params.get("relation"):
        plan["relation"] = params.get("relation")
    if params.get("event_type"):
        plan["event_type"] = params.get("event_type")
    if params.get("spouse_name"):
        plan["honoree_name"] = params.get("spouse_name")
    new_state = dict(state); new_state["plan"] = plan
    return new_state

def node_plan_event(state: BirthdayState):
    p = state.get("params", {})
    spouse = p.get("spouse_name", state.get("plan", {}).get("honoree_name") or "Spouse")
    budget = p.get("budget", 10000)
    relation = state.get("plan", {}).get("relation") or p.get("relation") or "family"
    event_type = state.get("plan", {}).get("event_type") or p.get("event_type") or "birthday"
    venue = "Quiet rooftop" if (state.get("profile", {}).get("meta", {}).get("stressors")) else "Trendy lounge"
    plan = dict(state.get("plan", {}))
    plan.update({
        "spouse_name": spouse,
        "honoree_name": plan.get("honoree_name") or spouse,
        "relation": relation,
        "event_type": event_type,
        "venue": venue,
        "theme": "Warm & Minimal",
        "budget": budget,
        "timeline": ["18:30 arrivals","19:15 toast","20:00 dinner","21:00 cake"],
    })
    new_state = dict(state); new_state["plan"] = plan
    return new_state

def node_compose_invites(state: BirthdayState):
    p = state.get("params", {}); invitees = p.get("invitees", [])
    honoree = state.get("plan", {}).get("honoree_name") or p.get("spouse_name", "Spouse")
    msg = compose_message("Hi {name},\nYou're invited to {spouse}'s surprise on {date} at {venue}. RSVP: {rsvp}", {"name": "{guest}", "spouse": honoree, "date": state.get("plan", {}).get("date"), "venue": state.get("plan", {}).get("venue","Venue"), "rsvp": "https://example.com/rsvp"})
    preview = msg.replace("{guest}", invitees[0] if invitees else "Guest")
    plan = dict(state.get("plan", {})); plan.update({"invite_message_template": msg, "invite_preview": preview, "invitees": invitees})
    new_state = dict(state); new_state["plan"] = plan
    return new_state

def node_send_invites(state: BirthdayState):
    plan = dict(state.get("plan", {})); invitees = plan.get("invitees", [])
    msg = plan.get("invite_message_template","{}").replace("{guest}", "Friend")
    result = send_invites(invitees, msg); plan["invite_result"] = result
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
