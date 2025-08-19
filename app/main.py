from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, date as _date
import json, asyncio
from app.schemas import PlanRequest, PlanResponse, AgentRunRequest, BirthdayPlanRequest, UpsertProfileRequest
from app.schemas import AgentCard
from app.profiles.demo import DEMO_PROFILES
from app.graphs.supervisor import SUPERVISOR_GRAPH, NODE_FUN, LINEAR_A, LINEAR_B, compute_day_context, router_order, supervisor_insights, make_supervisor_bullets_prompt
from app.graphs.birthday import BIRTHDAY_GRAPH
from typing import Dict, Any, Optional, List
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

    action = req.client_action or interpret_nl(req.utterance)
    target = req.target
    thread_id = req.thread_id or f"{req.profile_id}:nl:{int(datetime.now().timestamp())}"

    # If target auto and intent is birthday-related, route accordingly
    if target == "auto":
        if action.get("type", "").endswith("birthday_plan") or action.get("type") in {"edit_invite_tone", "edit_invite_text", "change_date", "change_venue", "adjust_budget", "add_invitees", "remove_invitees"}:
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
                "budget": action.get("budget", 10000),
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

        # Edits
        t = action.get("type")
        if t == "edit_invite_tone":
            style = action.get("style", "friendly"); brev = action.get("brevity", "medium")
            current = plan.get("invite_message_template") or "Hi {name},\nYou're invited to {spouse}'s surprise on {date} at {venue}. RSVP: {rsvp}"
            constraints = {
                "spouse": plan.get("spouse_name") or (req.plan or {}).get("spouse_name") or "{spouse}",
                "date": plan.get("date") or "{date}",
                "venue": plan.get("venue") or "{venue}",
            }
            revised = rewrite_invite_template(style, brev, current, constraints)
            plan["invite_message_template"] = revised
            # refresh preview
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
        elif t == "change_date":
            if action.get("event_date"): plan["date"] = action["event_date"]; summary = "Changed date."
        elif t == "change_venue":
            if action.get("venue"): plan["venue"] = action["venue"]; summary = "Changed venue."
        elif t == "adjust_budget":
            if action.get("budget"): plan["budget"] = action["budget"]; summary = "Adjusted budget."
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
# The WS streams a JSON message every time a node finishes. The client can render cards as they arrive.

@app.websocket("/ws/plan/day")
async def ws_plan_day(ws: WebSocket):
    await ws.accept()
    try:
        raw = await ws.receive_text()
        payload = json.loads(raw)
        profile_id = payload.get("profile_id"); date = payload.get("date")
        profile = DEMO_PROFILES.get(profile_id)
        if not profile:
            await ws.send_json({"type": "error", "message": f"Unknown profile_id {profile_id}"}); await ws.close(); return
        date = date or datetime.now().date().isoformat()

        # Compute day context and route
        ctx = compute_day_context(profile, date)
        order = router_order(profile, ctx)

        state = {"messages": [], "profile": profile, "request": {"date": date, "context": ctx}, "now": datetime.now().isoformat(), "outputs": {}, "logs": []}
        # supervisor first
        sup = supervisor_insights(profile, ctx, bullets_override=payload.get("supervisor_insights_bullets"))
        state.setdefault("outputs", {}).setdefault("cards", []).append(sup.dict())
        await ws.send_json({"type": "card", "node": "supervisor", "cards": [sup.dict()]})

        for node_name in order:
            state = NODE_FUN[node_name](state)
            # send incremental card for this node
            new_cards = state.get("outputs", {}).get("cards", [])
            await ws.send_json({"type": "card", "node": node_name, "cards": new_cards[-1:]})
            await asyncio.sleep(0)

        await ws.send_json({"type": "done", "planned_sequence": ["supervisor"] + order})
        await ws.close()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
        finally:
            await ws.close()

@app.post("/api/prompts/build", response_model=BuildPromptResponse)
def build_prompt(req: BuildPromptRequest):
    if req.kind == "supervisor_bullets":
        # req.prompt must already include the day-context prompt (client can also reconstruct)
        if not req.prompt:
            raise HTTPException(400, "prompt is required for supervisor_bullets")
        return BuildPromptResponse(prompt=build_bullets_prompt(req.prompt, count=3))
    elif req.kind == "interpret_nl":
        if not req.utterance:
            raise HTTPException(400, "utterance is required for interpret_nl")
        return BuildPromptResponse(prompt=build_interpret_nl_prompt(req.utterance))
    elif req.kind == "rewrite_invite":
        if not (req.style and req.brevity and req.current_template):
            raise HTTPException(400, "style, brevity, and current_template are required for rewrite_invite")
        return BuildPromptResponse(prompt=build_rewrite_invite_prompt(req.style, req.brevity, req.current_template))
    else:
        raise HTTPException(400, f"Unknown kind {req.kind}")

@app.get("/api/prompts/supervisor")
def get_supervisor_prompt(profile_id: str, date: Optional[str] = None):
    profile = DEMO_PROFILES.get(profile_id)
    if not profile:
        raise HTTPException(404, f"Unknown profile_id {profile_id}")
    date = date or datetime.now().date().isoformat()
    ctx = compute_day_context(profile, date)
    prompt = make_supervisor_bullets_prompt(profile, ctx)
    return {"prompt": build_bullets_prompt(prompt, count=3), "context": ctx}
