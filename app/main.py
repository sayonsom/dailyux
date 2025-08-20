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

    init = {"messages": [], "profile": profile, "request": {"date": date, "context": ctx}, "now": datetime.now().isoformat(), "outputs": {}, "logs": []}
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

# ---------------- WebSocket: incremental card updates ----------------

# ---------------- Date/Time update endpoint ----------------
from app.schemas import DateTimeUpdateRequest, DateTimeUpdateResponse


def _validate_date_str(date_str: str) -> None:
    try:
        # Must be YYYY-MM-DD
        datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        raise HTTPException(400, "Invalid date format. Use YYYY-MM-DD.")


def _ensure_not_past(date_str: str) -> None:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if d < datetime.now().date():
        raise HTTPException(400, "Date cannot be in the past.")


@app.post("/api/datetime/update", response_model=DateTimeUpdateResponse)
def datetime_update(req: DateTimeUpdateRequest):
    profile = DEMO_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(404, f"Unknown profile_id {req.profile_id}")

    plan = _get_persisted_plan(req.thread_id) or {}
    if not plan:
        # Create a seed plan so calendar node has context
        plan = {"invitees": []}

    action = req.action

    if action == "change_date":
        if not req.new_date:
            raise HTTPException(400, "new_date is required for change_date action")
        _validate_date_str(req.new_date)
        _ensure_not_past(req.new_date)
        # Update plan date and clear availability/time so graph recomputes
        plan["date"] = req.new_date
        plan.pop("availability", None)
        plan.pop("time_options", None)
        plan.pop("time", None)
        message = "Changed date and refreshed options."
    elif action == "refresh_times":
        # Keep date as-is, just clear times to force refresh
        if not plan.get("date"):
            # If missing, try use current_date
            if req.current_date:
                _validate_date_str(req.current_date)
                plan["date"] = req.current_date
            else:
                raise HTTPException(400, "current_date is required when plan has no date")
        message = "Refreshed time options."
        plan.pop("availability", None)
        plan.pop("time_options", None)
        plan.pop("time", None)
    else:
        raise HTTPException(400, "Unsupported action. Use change_date or refresh_times.")

    # Re-run the graph to recompute availability/time options and dependents
    state = {"messages": [], "profile": profile, "params": {"event_date": plan.get("date")}, "plan": plan}
    config = {"configurable": {"thread_id": req.thread_id, "checkpoint_ns": "birthday"}}
    result = BIRTHDAY_GRAPH.invoke(state, config=config)
    updated = result.get("plan", plan)

    # Error case: no availability -> time options could be empty
    if not updated.get("time_options"):
        # Provide a graceful message; still return plan so UI can react
        msg = "No time slots available for the selected date. Try another date."
    else:
        msg = message

    PLAN_STORE[req.thread_id] = updated
    return DateTimeUpdateResponse(ok=True, message=msg, plan=updated, thread_id=req.thread_id)

# ---------------- v1: Recommendations API ----------------
from app.schemas import (
    ProfileModel, EventModel, Theme, Venue, RecommendationsRequest, RecommendationsResponse,
    CreateJobRequest, JobStatusResponse, FeedbackRequest, VenuesSearchRequest,
)
from app.recommendations.places_gateway import search_places
from app.recommendations.llm_orchestrator import generate_themes, rerank_venues, MODEL_VERSION

# In-memory stores (replace with DB/Redis)
_PROFILE_STORE: Dict[str, Dict[str, Any]] = {}
_EVENT_STORE: Dict[str, Dict[str, Any]] = {}
_RECS_STORE: Dict[str, Dict[str, Any]] = {}
_FEEDBACK_STORE: List[Dict[str, Any]] = []
_JOBS: Dict[str, Dict[str, Any]] = {}


def _now_ts() -> int:
    return int(datetime.now().timestamp())


@app.post("/api/v1/profiles")
def v1_upsert_profile(profile: ProfileModel):
    _PROFILE_STORE[profile.profileId] = json.loads(profile.model_dump_json())
    return {"ok": True}


@app.post("/api/v1/events")
def v1_create_event(event: EventModel):
    if not event.eventId:
        event.eventId = f"evt_{_now_ts()}"
    # Basic derive age if possible
    prof = _PROFILE_STORE.get(event.profileId) or DEMO_PROFILES.get(event.profileId, {})
    b = (prof or {}).get("birthdate")
    if b and event.targetDate and len(b) >= 10:
        try:
            bd = datetime.fromisoformat(b[:10]).date()
            td = datetime.fromisoformat(event.targetDate[:10]).date()
            event.computedAgeAtEvent = td.year - bd.year - ((td.month, td.day) < (bd.month, bd.day))
        except Exception:
            pass
    _EVENT_STORE[event.eventId] = json.loads(event.model_dump_json())
    return {"ok": True, "eventId": event.eventId}


def _pull_profile_event(eventId: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ev = _EVENT_STORE.get(eventId)
    if not ev:
        raise HTTPException(404, f"Unknown eventId {eventId}")
    prof = _PROFILE_STORE.get(ev["profileId"]) or DEMO_PROFILES.get(ev["profileId"]) or {}
    return prof, ev


@app.post("/api/v1/events/{eventId}/recommendations", response_model=RecommendationsResponse)
def v1_recommendations(eventId: str, req: RecommendationsRequest):
    profile, event = _pull_profile_event(eventId)

    # Cache key
    cache_key = json.dumps({"profileId": event.get("profileId"), "eventId": eventId, "k1": req.topKThemes, "k2": req.topKVenues}, sort_keys=True)
    if not req.forceRefresh and cache_key in _RECS_STORE:
        payload = _RECS_STORE[cache_key]
        return RecommendationsResponse(**payload)

    # 1) Themes via LLM (k-1) and append a deterministic Home/Quiet theme
    k_llm = max(1, req.topKThemes - 1)
    from app.recommendations.llm_orchestrator import rerank_themes, make_home_theme, build_query_from_theme, price_from_budget
    themes = generate_themes(profile, event, n=max(5, k_llm))
    themes_ranked = rerank_themes(themes, profile, event)
    quiet_home = make_home_theme(event)
    top_themes = (themes_ranked[:k_llm] + [quiet_home])[: req.topKThemes]

    # 2) For the best non-home theme, fetch venues with theme-aware query
    used_tools = ["llm.generate_themes", "places.search", "llm.rerank_venues"]
    venues_all: List[Dict[str, Any]] = []

    # Prefer precise lat/lng from profile.homeLocation if present; ignore cityOverride string here
    home = profile.get("homeLocation") or {}
    lat = (home.get("lat") if isinstance(home, dict) else None) or 12.9716
    lng = (home.get("lng") if isinstance(home, dict) else None) or 77.5946
    radius = int(((event.get("radiusKm") or 3) * 1000))

    best_theme = next((t for t in top_themes if t.get("id") != "theme_home_quiet"), None) or top_themes[0]
    if best_theme.get("id") != "theme_home_quiet":
        query = build_query_from_theme(best_theme, event)
        cuisines = (profile.get("preferences") or {}).get("cuisinesLiked") or []
        params = {
            "query": query,
            "lat": lat,
            "lng": lng,
            "radius": radius,
            "priceLevel": price_from_budget(event.get("budgetPerPerson")),
            "cuisine": cuisines[0] if cuisines else None,
        }
        results = search_places(params)
        for r in results:
            r["themeId"] = best_theme.get("id")
            venues_all.append(r)

        # 3) Rerank globally with LLM by best theme match per venue
        reranked = rerank_venues(profile, event, best_theme, venues_all, top_k=req.topKVenues)
    else:
        reranked = []

    resp = RecommendationsResponse(
        themes=[Theme(**t) for t in top_themes],
        venues=[Venue(**v) for v in reranked],
        usedTools=used_tools,
        modelVersion=MODEL_VERSION,
        ttlSeconds=2 * 60,
        recId=f"rec_{_now_ts()}"
    )
    _RECS_STORE[cache_key] = json.loads(resp.model_dump_json())
    return resp


@app.post("/api/v1/recommendation-jobs")
def v1_create_job(req: CreateJobRequest):
    job_id = f"job_{_now_ts()}"
    _JOBS[job_id] = {"status": "pending", "req": json.loads(req.model_dump_json())}

    async def _run():
        _JOBS[job_id]["status"] = "running"
        try:
            r = await _compute_recs_async(req.eventId, req.topKThemes, req.topKVenues)
            _JOBS[job_id]["status"] = "complete"
            _JOBS[job_id]["result"] = r
        except Exception as e:
            _JOBS[job_id]["status"] = "failed"
            _JOBS[job_id]["error"] = str(e)

    asyncio.create_task(_run())
    return {"jobId": job_id}


async def _compute_recs_async(eventId: str, k1: int, k2: int) -> Dict[str, Any]:
    # Simple awaitable wrapper that uses sync function
    loop = asyncio.get_event_loop()
    def _sync():
        payload = v1_recommendations(eventId, RecommendationsRequest(topKThemes=k1, topKVenues=k2, forceRefresh=True))
        return json.loads(payload.model_dump_json())
    return await loop.run_in_executor(None, _sync)


@app.get("/api/v1/recommendation-jobs/{jobId}", response_model=JobStatusResponse)
def v1_job_status(jobId: str):
    job = _JOBS.get(jobId)
    if not job:
        raise HTTPException(404, "jobId not found")
    res = job.get("result")
    return JobStatusResponse(jobId=jobId, status=job["status"], result=RecommendationsResponse(**res) if res else None, error=job.get("error"))


@app.post("/api/v1/recommendations/{recId}/feedback")
def v1_feedback(recId: str, req: FeedbackRequest):
    _FEEDBACK_STORE.append({"recId": recId, **json.loads(req.model_dump_json()), "ts": _now_ts()})
    return {"ok": True}


@app.get("/api/v1/venues/search")
def v1_venues_search(lat: float, lng: float, radius: int = 3000, query: Optional[str] = None, cuisines: Optional[str] = None, priceLevel: Optional[int] = None):
    params: Dict[str, Any] = {"lat": lat, "lng": lng, "radius": radius, "query": query or "restaurant"}
    if cuisines:
        params["cuisine"] = cuisines.split(",")[0]
    if priceLevel is not None:
        params["priceLevel"] = priceLevel
    res = search_places(params)
    return {"results": res}
