from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, date as _date
import json, asyncio, importlib, os
from app.schemas import PlanRequest, PlanResponse, AgentRunRequest, BirthdayPlanRequest, UpsertProfileRequest
from app.schemas import AgentCard
from app.profiles.demo import DEMO_PROFILES
from app.graphs.supervisor import SUPERVISOR_GRAPH, NODE_FUN, LINEAR_A, LINEAR_B, compute_day_context, router_order, supervisor_insights, make_supervisor_bullets_prompt
from app.graphs.birthday import BIRTHDAY_GRAPH
from typing import Dict, Any, Optional, List, Tuple
from app.schemas import NaturalCommandRequest, NaturalCommandResponse, BuildPromptRequest, BuildPromptResponse
from app.llm.llm import interpret_nl, build_interpret_nl_prompt, build_bullets_prompt
from app.tools.comms import rewrite_invite_template, compose_message, render_invite_preview, build_rewrite_invite_prompt
from app.settings import settings
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Agentic Day Planner (LangGraph + Gemini)")

# Permissive CORS (dev): allow all origins, methods, and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

# Serve static files for quick test UI (optional)
try:
    STATIC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "static"))
    if os.path.isdir(STATIC_DIR):
        _sf = importlib.import_module("starlette.staticfiles")
        app.mount("/static", _sf.StaticFiles(directory=STATIC_DIR), name="static")
except Exception:
    pass

# ---------------- Simple in-memory persistence ----------------
PLAN_STORE: Dict[str, Dict[str, Any]] = {}

# Helper: derive spouse name from profile metadata
_def_spouse_tokens = {"spouse", "wife", "husband", "partner"}


def _derive_spouse_name(profile: Dict[str, Any]) -> Optional[str]:
    try:
        fam = (profile or {}).get("meta", {}).get("family", [])
        for m in fam:
            rel = (m.get("relation") or "").strip().lower()
            if rel in _def_spouse_tokens:
                return m.get("name")
    except Exception:
        pass
    return None

# Parse MM-DD or YYYY-MM-DD into a date in the next `horizon_days` days, else None

def _parse_upcoming(date_str: str, today: _date, horizon_days: int = 60) -> Optional[_date]:
    try:
        if len(date_str) == 10:
            dt = datetime.fromisoformat(date_str).date()
        else:
            dt = datetime.fromisoformat(f"{today.year}-{date_str}").date()
        # If already passed this year, consider next year
        if dt < today:
            try:
                dt = datetime.fromisoformat(f"{today.year + 1}-{date_str}").date()
            except Exception:
                pass
        if 0 <= (dt - today).days <= horizon_days:
            return dt
    except Exception:
        return None
    return None


def _pick_upcoming_birthday(profile: Dict[str, Any], horizon_days: int = 60) -> Optional[Dict[str, Any]]:
    today = datetime.now().date()
    best: Optional[Dict[str, Any]] = None
    best_days = 10**9
    meta = (profile or {}).get("meta", {})
    # family
    for f in meta.get("family", []) or []:
        b = f.get("birthday")
        if not b:
            continue
        dt = _parse_upcoming(b, today, horizon_days)
        if not dt:
            continue
        days = (dt - today).days
        if days < best_days:
            best_days = days
            best = {"name": f.get("name"), "relation": f.get("relation", "family"), "date": dt.isoformat(), "type": "birthday"}
    # colleagues
    for c in meta.get("colleagues", []) or []:
        b = c.get("birthday")
        if not b:
            continue
        dt = _parse_upcoming(b, today, horizon_days)
        if not dt:
            continue
        days = (dt - today).days
        if days < best_days:
            best_days = days
            best = {"name": c.get("name"), "relation": c.get("role", "colleague"), "date": dt.isoformat(), "type": "birthday"}
    return best


def _get_persisted_plan(thread_id: str) -> Optional[Dict[str, Any]]:
    plan = PLAN_STORE.get(thread_id)
    if plan:
        return plan
    # Fallback to graph checkpointer state if available
    try:
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
        snap = BIRTHDAY_GRAPH.get_state(config)  # type: ignore[attr-defined]
        values = getattr(snap, "values", None) or getattr(snap, "last_values", None) or snap
        if isinstance(values, dict):
            plan = values.get("plan")
            if isinstance(plan, dict):
                PLAN_STORE[thread_id] = plan
                return plan
    except Exception:
        pass
    return None


def _normalize_budget(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        s = val.strip().lower()
        if s in ("low", "small", "budget"): return 3000
        if s in ("medium", "med", "mid"): return 10000
        if s in ("high", "large", "premium"): return 25000
        try:
            return int(s)
        except Exception:
            return 10000
    return 10000


# Collect completed home-ops results for this profile

def _collect_home_ops_results(profile_id: str) -> List[Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    prefix = f"{profile_id}:birthday:"
    for tid, plan in PLAN_STORE.items():
        if not tid.startswith(prefix):
            continue
        ops = (plan or {}).get("ops", {}) or {}
        for kind, res in ops.items():
            # Keep latest by kind (simple overwrite is fine for demo)
            results[kind] = {"kind": kind, "result": res}
    return list(results.values())


@app.get("/health")
def health_check():
    """Health check endpoint for container orchestration"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/profiles")
def list_profiles():
    return {"profiles": list(DEMO_PROFILES.keys())}


@app.post("/api/profiles/upsert")
def upsert_profile(req: UpsertProfileRequest):
    DEMO_PROFILES[req.profile_id] = req.profile_json
    return {"ok": True, "count": len(DEMO_PROFILES)}


@app.post("/api/plan/day", response_model=PlanResponse)
def plan_day(req: PlanRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile: raise HTTPException(404, f"Unknown profile_id {req.profile_id}")
    date = req.date or datetime.now().date().isoformat()

    # Compute day context and route
    ctx = compute_day_context(profile, date)
    order = router_order(profile, ctx)

    # Include any completed home-ops results for surfacing as cards
    home_ops_results = _collect_home_ops_results(req.profile_id)

    init = {"messages": [], "profile": profile, "request": {"date": date, "context": ctx, "home_ops_results": home_ops_results}, "now": datetime.now().isoformat(), "outputs": {}, "logs": []}
    # Checkpointer keys
    config = {"configurable": {"thread_id": f"{req.profile_id}:{date}", "checkpoint_ns": "plan_day"}}

    # Execute in-process in decided order (explicit execution for better streaming parity)
    state = init
    # Supervisor insights first
    sup = supervisor_insights(profile, ctx, bullets_override=req.supervisor_insights_bullets)
    state.setdefault("outputs", {}).setdefault("cards", []).append(sup.dict())
    for node_name in order:
        state = NODE_FUN[node_name](state)

    cards = sorted(state.get("outputs", {}).get("cards", []), key=lambda c: c.get("priority", 5))
    rationale = f"Profile role={ctx.get('role')}, night_owl={ctx.get('night_owl')}, load={ctx.get('day_load')}; sequence={['SupervisorAgent'] + order}"
    return PlanResponse(date=date, profile_id=req.profile_id, timezone=profile.get("timezone","Asia/Kolkata"), cards=[AgentCard(**c) for c in cards], rationale=rationale)


@app.post("/api/agents/run")
def run_agent(req: AgentRunRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile: raise HTTPException(404, f"Unknown profile_id {req.profile_id}")
    # Simple direct map instead of above trick:
    amap = {
        "WorkLifeAgent": "work_life", "LifeAfterWorkAgent": "life_after_work", "RelaxationAgent": "relaxation",
        "FitnessAgent": "fitness", "TrafficAgent": "traffic", "GettingStartedAgent": "getting_started", "HobbyAgent": "hobby",
        # New agents
        "NutritionAgent": "nutrition", "FinanceErrandsAgent": "finance_errands", "LearningAgent": "learning", "CelebrationsAgent": "celebrations",
    }
    node_name = amap[req.agent]
    node = NODE_FUN[node_name]
    st = {"profile": profile, "request": req.context, "outputs": {"cards": []}}
    out = node(st)
    return {"cards": out["outputs"]["cards"], "logs": [f"ran {node_name}"]}


@app.post("/api/task/birthday")
def birthday_task(req: BirthdayPlanRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile: raise HTTPException(404, f"Unknown profile_id {req.profile_id}")
    # Sensible defaults
    spouse = req.spouse_name or ""
    if spouse in {"Spouse", "Wife", "Husband", "Partner", ""}:
        spouse = _derive_spouse_name(profile) or spouse or "Spouse"
    params = req.dict(); params["spouse_name"] = spouse

    # Normalize budget tiers/strings to numeric
    params["budget"] = _normalize_budget(params.get("budget"))

    # If no explicit event_date, try to pick the nearest upcoming birthday from profile context
    if not params.get("event_date"):
        cand = _pick_upcoming_birthday(profile)
        if cand:
            params["spouse_name"] = cand.get("name") or params.get("spouse_name")
            params["event_date"] = cand.get("date")
            params["relation"] = cand.get("relation", "family")
            params["event_type"] = cand.get("type", "birthday")

    state = {"messages": [], "profile": profile, "params": params, "plan": {}}
    # Provide required configurable keys for checkpointer
    thread_id = f"{req.profile_id}:birthday:{int(datetime.now().timestamp())}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
    result = BIRTHDAY_GRAPH.invoke(state, config=config)
    plan = result.get("plan", {})
    PLAN_STORE[thread_id] = plan
    return {"plan": plan, "thread_id": thread_id}

# ---------------- Natural Language endpoint ----------------


@app.post("/api/nl", response_model=NaturalCommandResponse)
def nl_command(req: NaturalCommandRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile: raise HTTPException(404, f"Unknown profile_id {req.profile_id}")

    action = req.client_action or interpret_nl(req.utterance) or {}
    target = req.target
    thread_id = req.thread_id or f"{req.profile_id}:nl:{int(datetime.now().timestamp())}"

    # If target auto and intent is birthday-related, route accordingly
    if target == "auto":
        if (action.get("type", "").endswith("birthday_plan") or action.get("type") in {"edit_invite_tone", "edit_invite_text", "change_date", "change_venue", "change_theme", "confirm_theme_venue", "choose_time", "confirm_invitees", "confirm_send", "adjust_budget", "add_invitees", "remove_invitees"}):
            target = "birthday"
        else:
            target = "agent"

    # Birthday flow
    if target == "birthday":
        # Load existing plan from request, store, or checkpointer
        plan: Dict[str, Any] = req.plan or _get_persisted_plan(thread_id) or {}
        summary = ""

        # If starting or no plan exists, run graph to initialize
        if action.get("type") == "start_birthday_plan" or not plan:
            cand = _pick_upcoming_birthday(profile)
            params = {
                "profile_id": req.profile_id,
                "spouse_name": action.get("spouse_name") or (cand.get("name") if cand else None) or _derive_spouse_name(profile) or "Spouse",
                "event_date": action.get("event_date") or (cand.get("date") if cand else None),
                "budget": _normalize_budget(action.get("budget", 10000)),
                "invitees": action.get("invitees", []),
            }
            if cand:
                params["relation"] = cand.get("relation", "family")
                params["event_type"] = cand.get("type", "birthday")
            state = {"messages": [], "profile": profile, "params": params, "plan": plan}
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
            result = BIRTHDAY_GRAPH.invoke(state, config=config)
            plan = result.get("plan", {})
            summary = "Started birthday plan."

        # Apply edits / confirmations
        t = action.get("type")
        if t == "change_theme" and action.get("theme"):
            plan["theme"] = action["theme"]; plan["stage"] = "review_theme_venue"; summary = "Changed theme."
        elif t == "change_venue" and action.get("venue"):
            plan["venue"] = action["venue"]; plan["stage"] = "review_theme_venue"; summary = "Changed venue."
        elif t == "confirm_theme_venue":
            plan["stage"] = "theme_venue_confirmed"; summary = "Confirmed theme and venue."
        elif t == "choose_time" and action.get("time"):
            plan["time"] = action["time"]; summary = f"Selected time {plan['time']}."
        elif t == "change_date" and action.get("event_date"):
            plan["date"] = action["event_date"]; plan.pop("availability", None); plan.pop("time_options", None); plan.pop("time", None)
            summary = "Changed date."
        elif t == "adjust_budget" and action.get("budget"):
            plan["budget"] = _normalize_budget(action["budget"]); summary = "Adjusted budget."
        elif t == "add_invitees":
            emails = action.get("emails", [])
            if emails:
                plan.setdefault("invitees", [])
                for e in emails:
                    if e not in plan["invitees"]: plan["invitees"].append(e)
                summary = f"Added {len(emails)} invitees."
        elif t == "remove_invitees":
            emails = set(action.get("emails", []))
            if emails and plan.get("invitees"):
                plan["invitees"] = [e for e in plan["invitees"] if e not in emails]
                summary = f"Removed {len(emails)} invitees."
        elif t == "confirm_invitees":
            plan["stage"] = "invitees_confirmed"; summary = "Confirmed invitees."
        elif t == "edit_invite_tone":
            style = action.get("style", "friendly"); brev = action.get("brevity", "medium")
            current = plan.get("invite_message_template") or "Hi {name},\nYou're invited to {spouse}'s surprise on {date} at {venue}. RSVP: {rsvp}"
            constraints = {
                "spouse": plan.get("spouse_name") or (req.plan or {}).get("spouse_name") or "{spouse}",
                "date": plan.get("date") or "{date}",
                "venue": plan.get("venue") or "{venue}",
            }
            revised = rewrite_invite_template(style, brev, current, constraints)
            plan["invite_message_template"] = revised
            invitees = plan.get("invitees", (req.plan or {}).get("invitees", []))
            preview = render_invite_preview(revised, invitees, {"spouse": constraints.get("spouse"), "date": constraints.get("date"), "venue": constraints.get("venue"), "rsvp": "https://example.com/rsvp"})
            plan["invite_preview"] = preview
            summary = f"Updated invite tone to {style}/{brev}."
        elif t == "edit_invite_text":
            tmpl = action.get("template")
            if tmpl:
                plan["invite_message_template"] = tmpl
                invitees = plan.get("invitees", (req.plan or {}).get("invitees", []))
                preview = render_invite_preview(tmpl, invitees, {"spouse": plan.get("spouse_name","Spouse"), "date": plan.get("date","{date}"), "venue": plan.get("venue","{venue}"), "rsvp": "https://example.com/rsvp"})
                plan["invite_preview"] = preview
                summary = "Rewrote invite template."
        elif t == "confirm_send":
            plan["stage"] = "ready_to_send"; summary = "Ready to send invites."

        # Re-invoke the graph after edits to advance stages or recompute options
        state = {"messages": [], "profile": profile, "params": {"invitees": plan.get("invitees", [])}, "plan": plan}
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
        result = BIRTHDAY_GRAPH.invoke(state, config=config)
        plan = result.get("plan", plan)

        # Persist plan in memory store
        PLAN_STORE[thread_id] = plan
        return NaturalCommandResponse(ok=True, summary=summary or "No changes.", plan=plan, thread_id=thread_id)

    # Agent flow: map utterance or hint to an agent and run it once
    amap_kw = {
        "traffic": "traffic", "commute": "traffic",
        "work": "work_life", "meeting": "work_life",
        "fitness": "fitness", "gym": "fitness",
        "relax": "relaxation", "unwind": "relaxation",
        "hobby": "hobby", "learn": "learning", "study": "learning",
        "nutrition": "nutrition", "diet": "nutrition",
        "finance": "finance_errands", "errand": "finance_errands",
        "evening": "life_after_work", "celebration": "celebrations", "party": "celebrations",
        "start": "getting_started", "morning": "getting_started",
    }
    node_name = None
    if req.agent:
        # If caller specifies, try exact map to NODE_FUN keys
        reverse = {
            "WorkLifeAgent": "work_life", "LifeAfterWorkAgent": "life_after_work", "RelaxationAgent": "relaxation",
            "FitnessAgent": "fitness", "TrafficAgent": "traffic", "GettingStartedAgent": "getting_started", "HobbyAgent": "hobby",
            "NutritionAgent": "nutrition", "FinanceErrandsAgent": "finance_errands", "LearningAgent": "learning", "CelebrationsAgent": "celebrations",
        }
        node_name = reverse.get(req.agent)
    if node_name is None:
        low = req.utterance.lower()
        for k, v in amap_kw.items():
            if k in low:
                node_name = v; break
    if node_name is None:
        return NaturalCommandResponse(ok=True, summary="No matching agent.", cards=None, thread_id=thread_id)

    node = NODE_FUN[node_name]
    st = {"profile": profile, "request": {}, "outputs": {"cards": []}}
    out = node(st)
    cards = [AgentCard(**c) for c in out.get("outputs", {}).get("cards", [])]
    return NaturalCommandResponse(ok=True, summary=f"Ran {node_name}.", cards=cards, thread_id=thread_id)

# ---------------- Persistence helpers ----------------


@app.get("/api/nl/plan")
def get_nl_plan(profile_id: str, thread_id: str):
    if profile_id not in DEMO_PROFILES:
        raise HTTPException(404, f"Unknown profile_id {profile_id}")
    plan = _get_persisted_plan(thread_id)
    if not plan:
        raise HTTPException(404, f"No plan found for thread_id {thread_id}")
    return {"ok": True, "plan": plan, "thread_id": thread_id}


@app.post("/api/nl/plan/save")
def save_nl_plan(payload: Dict[str, Any]):
    thread_id = payload.get("thread_id")
    plan = payload.get("plan")
    if not thread_id or not isinstance(plan, dict):
        raise HTTPException(400, "thread_id and plan required")
    PLAN_STORE[thread_id] = plan
    return {"ok": True, "thread_id": thread_id}

# ---------------- Timeline simulation endpoints ----------------

from app.schemas import SimTickRequest, SimTickResponse, SimStatusResponse, TimelineTask


def _run_task(kind: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate task execution; in real world, call sub-agents/tools."""
    if kind == "decide_menu":
        guests = len(plan.get("invitees", [])) or 8
        veg = max(2, guests // 3)
        dishes = ["Paneer Tikka", "Hakka Noodles", "Veg Biryani", "Chicken Kebab", "Gulab Jamun"]
        return {"guests": guests, "veg": veg, "dishes": dishes}
    if kind == "grocery_shopping":
        menu = (plan.get("ops", {}) or {}).get("decide_menu") or {}
        dishes = menu.get("dishes", ["Snacks", "Drinks"])
        items = [f"Ingredients for {d}" for d in dishes] + ["Paper plates", "Napkins", "Soda", "Ice"]
        return {"list": items, "ordered": True, "eta": "T-12h"}
    if kind == "wifi_access":
        ssid = f"Guest-{plan.get('spouse_name','Party')}"
        return {"ssid": ssid, "password": "party@123", "qr": "data:image/png;base64,...."}
    if kind == "secure_locks":
        return {"locks_engaged": True, "time": datetime.now().isoformat()}
    if kind == "post_cleanup":
        return {"robot_started": True, "rooms": ["Living Room", "Dining", "Kitchen"], "duration_min": 60}
    return {"ok": True}


@app.get("/api/timeline/status", response_model=SimStatusResponse)
def get_timeline_status(thread_id: str):
    plan = _get_persisted_plan(thread_id)
    if not plan:
        raise HTTPException(404, f"No plan for thread_id {thread_id}")
    tasks = plan.get("ops_timeline", [])
    return SimStatusResponse(ok=True, thread_id=thread_id, now=datetime.now().isoformat(), tasks=[TimelineTask(**t) for t in tasks])


@app.post("/api/timeline/tick", response_model=SimTickResponse)
def tick_timeline(req: SimTickRequest):
    plan = _get_persisted_plan(req.thread_id)
    if not plan:
        raise HTTPException(404, f"No plan for thread_id {req.thread_id}")
    tasks: List[Dict[str, Any]] = plan.get("ops_timeline", []) or []
    now = datetime.fromisoformat(req.now) if req.now else datetime.now()

    processed: List[TimelineTask] = []
    steps = 0
    for t in tasks:
        if steps >= req.maxSteps:
            break
        if t.get("status") != "scheduled":
            continue
        try:
            sched = datetime.fromisoformat(t.get("scheduledAt"))
        except Exception:
            sched = now
        if sched <= now:
            t["status"] = "running"
            result = _run_task(t.get("kind"), plan)
            # accumulate in plan.ops
            plan.setdefault("ops", {})
            plan["ops"][t.get("kind")] = result
            t["result"] = result
            t["status"] = "done"
            processed.append(TimelineTask(**t))
            steps += 1

    # Persist updates
    plan["ops_timeline"] = tasks
    PLAN_STORE[req.thread_id] = plan

    remaining = len([t for t in tasks if t.get("status") == "scheduled"])
    return SimTickResponse(ok=True, thread_id=req.thread_id, now=now.isoformat(), processed=processed, remaining=remaining)

# ---------------- WebSocket: incremental card updates ----------------
from app.schemas import (
    BirthdayStartRequest, BirthdayPlanResponse, ThemeUpdateRequest, VenueUpdateRequest,
    DateUpdateRequest, TimeUpdateRequest, BudgetUpdateRequest,
    InviteesPutRequest, InviteesEmailsRequest, InvitesToneRequest, InvitesTextRequest,
    OrchestrateRequest, OrchestrateResponse,
)
from app.recommendations.places_gateway import search_places

# -------------- Helpers for organized endpoints --------------

def _ensure_plan(thread_id: str, profile_id: str) -> Dict[str, Any]:
    plan = _get_persisted_plan(thread_id)
    if not plan:
        raise HTTPException(404, f"No plan for thread_id {thread_id}")
    # Attach profile_id for ops
    plan.setdefault("profile_id", profile_id)
    return plan


def _advance_graph(thread_id: str, profile: Dict[str, Any], plan: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    state = {"messages": [], "profile": profile, "params": params, "plan": plan}
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
    result = BIRTHDAY_GRAPH.invoke(state, config=config)
    plan = result.get("plan", plan)
    PLAN_STORE[thread_id] = plan
    return plan


# -------------- Organized REST: Birthday endpoints --------------

@app.post("/api/birthdays", response_model=BirthdayPlanResponse)
def birthday_start(req: BirthdayStartRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(404, f"Unknown profile_id {req.profile_id}")
    # Reuse /api/task/birthday logic
    spouse = req.spouse_name or _derive_spouse_name(profile) or "Spouse"
    params = req.dict(); params["spouse_name"] = spouse
    params["budget"] = _normalize_budget(params.get("budget"))
    state = {"messages": [], "profile": profile, "params": params, "plan": {}}
    thread_id = f"{req.profile_id}:birthday:{int(datetime.now().timestamp())}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "birthday"}}
    result = BIRTHDAY_GRAPH.invoke(state, config=config)
    plan = result.get("plan", {})
    PLAN_STORE[thread_id] = plan
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.get("/api/birthdays/{thread_id}", response_model=BirthdayPlanResponse)
def birthday_get(thread_id: str, profile_id: str):
    plan = _ensure_plan(thread_id, profile_id)
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.patch("/api/birthdays/{thread_id}/theme", response_model=BirthdayPlanResponse)
def birthday_update_theme(thread_id: str, profile_id: str, req: ThemeUpdateRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["theme"] = req.theme; plan["stage"] = "review_theme_venue"
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.patch("/api/birthdays/{thread_id}/venue", response_model=BirthdayPlanResponse)
def birthday_update_venue(thread_id: str, profile_id: str, req: VenueUpdateRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["venue"] = req.venue; plan["stage"] = "review_theme_venue"
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.patch("/api/birthdays/{thread_id}/date", response_model=BirthdayPlanResponse)
def birthday_update_date(thread_id: str, profile_id: str, req: DateUpdateRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["date"] = req.event_date
    # reset scheduling bits
    for k in ["availability","time_options","time"]:
        plan.pop(k, None)
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.patch("/api/birthdays/{thread_id}/time", response_model=BirthdayPlanResponse)
def birthday_update_time(thread_id: str, profile_id: str, req: TimeUpdateRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["time"] = req.time
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.patch("/api/birthdays/{thread_id}/budget", response_model=BirthdayPlanResponse)
def birthday_update_budget(thread_id: str, profile_id: str, req: BudgetUpdateRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["budget"] = _normalize_budget(req.budget)
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.put("/api/birthdays/{thread_id}/invitees", response_model=BirthdayPlanResponse)
def birthday_put_invitees(thread_id: str, profile_id: str, req: InviteesPutRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["invitees"] = list(dict.fromkeys(req.invitees))
    plan = _advance_graph(thread_id, profile, plan, {"invitees": plan.get("invitees", [])})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invitees/add", response_model=BirthdayPlanResponse)
def birthday_add_invitees(thread_id: str, profile_id: str, req: InviteesEmailsRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan.setdefault("invitees", [])
    for e in req.emails:
        if e not in plan["invitees"]:
            plan["invitees"].append(e)
    plan = _advance_graph(thread_id, profile, plan, {"invitees": plan.get("invitees", [])})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invitees/remove", response_model=BirthdayPlanResponse)
def birthday_remove_invitees(thread_id: str, profile_id: str, req: InviteesEmailsRequest):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    emails = set(req.emails)
    plan["invitees"] = [e for e in plan.get("invitees", []) if e not in emails]
    plan = _advance_graph(thread_id, profile, plan, {"invitees": plan.get("invitees", [])})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invitees/confirm", response_model=BirthdayPlanResponse)
def birthday_confirm_invitees(thread_id: str, profile_id: str):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["stage"] = "invitees_confirmed"
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invites/preview/tone", response_model=BirthdayPlanResponse)
def birthday_invites_tone(thread_id: str, profile_id: str, req: InvitesToneRequest):
    # Reuse existing NL helper to rewrite text
    plan = _ensure_plan(thread_id, profile_id)
    from app.tools.comms import rewrite_invite_template, render_invite_preview
    style, brev = req.style, req.brevity
    current = plan.get("invite_message_template") or "Hi {name},\nYou're invited to {spouse}'s surprise on {date} at {venue}. RSVP: {rsvp}"
    constraints = {"spouse": plan.get("spouse_name","Spouse"), "date": plan.get("date","{date}"), "venue": plan.get("venue","{venue}")}
    revised = rewrite_invite_template(style, brev, current, constraints)
    plan["invite_message_template"] = revised
    preview = render_invite_preview(revised, plan.get("invitees", []), {"spouse": constraints["spouse"], "date": constraints["date"], "venue": constraints["venue"], "rsvp": "https://example.com/rsvp"})
    plan["invite_preview"] = preview
    PLAN_STORE[thread_id] = plan
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invites/preview/text", response_model=BirthdayPlanResponse)
def birthday_invites_text(thread_id: str, profile_id: str, req: InvitesTextRequest):
    from app.tools.comms import render_invite_preview
    plan = _ensure_plan(thread_id, profile_id)
    plan["invite_message_template"] = req.template
    preview = render_invite_preview(req.template, plan.get("invitees", []), {"spouse": plan.get("spouse_name","Spouse"), "date": plan.get("date","{date}"), "venue": plan.get("venue","{venue}"), "rsvp": "https://example.com/rsvp"})
    plan["invite_preview"] = preview
    PLAN_STORE[thread_id] = plan
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invites/ready", response_model=BirthdayPlanResponse)
def birthday_invites_ready(thread_id: str, profile_id: str):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["stage"] = "ready_to_send"
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.post("/api/birthdays/{thread_id}/invites/send", response_model=BirthdayPlanResponse)
def birthday_invites_send(thread_id: str, profile_id: str):
    profile = DEMO_PROFILES.get(profile_id) or {}
    plan = _ensure_plan(thread_id, profile_id)
    plan["stage"] = "ready_to_send"
    plan = _advance_graph(thread_id, profile, plan, {})
    return BirthdayPlanResponse(thread_id=thread_id, plan=plan)


@app.get("/api/birthdays/{thread_id}/timeline", response_model=SimStatusResponse)
def birthday_timeline(thread_id: str, profile_id: str):
    plan = _ensure_plan(thread_id, profile_id)
    tasks = plan.get("ops_timeline", [])
    return SimStatusResponse(ok=True, thread_id=thread_id, now=datetime.now().isoformat(), tasks=[TimelineTask(**t) for t in tasks])


@app.post("/api/birthdays/{thread_id}/timeline/tick", response_model=SimTickResponse)
def birthday_timeline_tick(thread_id: str, profile_id: str, req: SimTickRequest):
    # Ensure we use the path thread_id, not the one in body
    req.thread_id = thread_id
    return tick_timeline(req)


# ---------------- Master Orchestrator ----------------

@app.post("/api/orchestrate/party", response_model=OrchestrateResponse)
def orchestrate_party(req: OrchestrateRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(404, f"Unknown profile_id {req.profile_id}")

    # 1) Start plan
    spouse = req.honoree_name or _derive_spouse_name(profile) or "Spouse"
    start = BirthdayStartRequest(profile_id=req.profile_id, spouse_name=spouse, event_date=req.event_date, budget=req.budget or 10000, invitees=req.invitees)
    start_resp = birthday_start(start)
    tid = start_resp.thread_id
    plan = start_resp.plan

    # 2) Venue research if auto/restaurant
    chosen_venue = plan.get("venue")
    if req.venueMode in ("restaurant", "auto") and (not chosen_venue or chosen_venue.lower().startswith("home") is False):
        # Try searching near profile home location (or default coords)
        loc = (profile.get("homeLocation") or {})
        lat = (loc.get("lat") or 37.7749); lng = (loc.get("lng") or -122.4194)
        places = search_places({"lat": lat, "lng": lng, "radius": 3000, "query": "birthday dinner", "priceLevel": 3})
        if places:
            chosen_venue = places[0]["name"]
            birthday_update_venue(tid, req.profile_id, VenueUpdateRequest(venue=chosen_venue))
            plan = _get_persisted_plan(tid) or plan

    # 3) If home explicitly requested, ensure Home is set
    if req.venueMode == "home":
        chosen_venue = "Home - Living room"
        birthday_update_venue(tid, req.profile_id, VenueUpdateRequest(venue=chosen_venue))
        plan = _get_persisted_plan(tid) or plan

    # 4) Pick a time (prefer 19:00 if available)
    time_opts = plan.get("time_options", [])
    pick = next((t for t in time_opts if t >= "18:30"), time_opts[0] if time_opts else "19:00")
    birthday_update_time(tid, req.profile_id, TimeUpdateRequest(time=pick))
    plan = _get_persisted_plan(tid) or plan

    # 5) Confirm theme/venue
    birthday_update_theme(tid, req.profile_id, ThemeUpdateRequest(theme=plan.get("theme") or "Warm & Minimal"))
    plan = _get_persisted_plan(tid) or plan
    birthday_invites_ready(tid, req.profile_id)
    plan = _get_persisted_plan(tid) or plan
    birthday_invites_send(tid, req.profile_id)
    plan = _get_persisted_plan(tid) or plan

    # 6) Optionally accelerate timeline
    notes = None
    if req.accelerateTo:
        tick = SimTickRequest(thread_id=tid, now=req.accelerateTo, maxSteps=10)
        tick_timeline(tick)
        plan = _get_persisted_plan(tid) or plan
        notes = f"Advanced timeline to {req.accelerateTo}"

    return OrchestrateResponse(ok=True, thread_id=tid, plan=plan, notes=notes)
