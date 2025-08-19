# Testing Guide: Agentic Day Planner via FastAPI Swagger UI

This guide shows how to test the agentic workflows using the built-in Swagger UI.

## 1) Start the API and open Swagger

Prereqs
- Python 3.10+
- Env vars: GOOGLE_API_KEY, optional GEMINI_MODEL (default: gemini-1.5-pro), TZ (default: Asia/Kolkata)

Run locally
```bash
pip install -r requirements.txt
export GOOGLE_API_KEY="<your-key>"
uvicorn app.main:app --reload
```
Open Swagger: http://127.0.0.1:8000/docs

Docker (optional)
- See `README-Docker.md` for container-based setup.

## 2) Seed/check profiles

Built-in demo profiles: `Ravindra`, `Mohan`, `Riktesh`.

From Swagger:
- GET `/api/profiles` → verify available `profile_id`s
- POST `/api/profiles/upsert` to add your own profile
```json
{
  "profile_id": "Alice",
  "profile_json": { "meta": {"role": "Engineer"}, "timezone": "Asia/Kolkata", "days": {"Day_1": {"09:00": "Standup"}} }
}
```

## 3) Health check
- GET `/health` → should return `{ "status": "healthy", ... }`

## 4) Plan a Day workflow
- POST `/api/plan/day`
Request body
```json
{ "profile_id": "Ravindra", "date": "2025-08-19" }
```
Notes
- Response includes `timezone`, `cards` (AgentCard[]), and `rationale`.
- Cards are sorted by priority.

## 5) Run a single agent
- POST `/api/agents/run`
- Valid `agent` values:
  - WorkLifeAgent, LifeAfterWorkAgent, RelaxationAgent, FitnessAgent, TrafficAgent, GettingStartedAgent, HobbyAgent, NutritionAgent, FinanceErrandsAgent, LearningAgent, CelebrationsAgent
Example
```json
{
  "profile_id": "Ravindra",
  "agent": "FitnessAgent",
  "context": {}
}
```

## 6) Natural language agent router
- POST `/api/nl`
- Use `target: "auto"` to auto-route based on keywords, or specify `target: "agent"` with `agent`, or `target: "birthday"` to operate on party planning.

Examples (auto-route to agents)
```json
{ "profile_id": "Ravindra", "target": "auto", "utterance": "Check traffic for my evening commute." }
```
```json
{ "profile_id": "Ravindra", "target": "auto", "utterance": "Suggest a short gym routine." }
```
Keyword map (auto):
- traffic/commute → Traffic
- work/meeting → WorkLife
- fitness/gym → Fitness
- relax/unwind → Relaxation
- hobby → Hobby, learn/study → Learning
- nutrition/diet → Nutrition
- finance/errand → FinanceErrands
- evening → LifeAfterWork, celebration/party → Celebrations
- start/morning → GettingStarted

Directly specify an agent
```json
{ "profile_id": "Ravindra", "target": "agent", "agent": "WorkLifeAgent", "utterance": "Plan my work block" }
```

## 7) Birthday planning workflow
Two ways to start:

A) Direct graph
- POST `/api/task/birthday`
```json
{
  "profile_id": "Mohan",
  "spouse_name": "Priya",
  "event_date": "2025-09-12",
  "budget": 20000,
  "invitees": ["a@example.com", "b@example.com"]
}
```
- Response returns `plan` and `thread_id`. Reuse `thread_id` for future edits.

B) Conversational (LLM-driven)
- POST `/api/nl` (requires GOOGLE_API_KEY to be set)
```json
{
  "profile_id": "Mohan",
  "target": "auto",
  "utterance": "Start a birthday plan for Priya on 12 Sep 2025 with a 20k budget and invite a@example.com, b@example.com"
}
```
- Copy `thread_id` from response for subsequent edits.

Follow-up edits (use the same `thread_id`)
- Change tone/length of invite
```json
{ "profile_id": "Mohan", "target": "birthday", "thread_id": "<from-previous>", "utterance": "Make the invite more formal and short" }
```
- Rewrite invite text explicitly
```json
{ "profile_id": "Mohan", "target": "birthday", "thread_id": "<from-previous>", "utterance": "Use this exact invite: Hi {name}, join us on {date} at {venue}. RSVP: {rsvp}" }
```
- Change date / venue / budget
```json
{ "profile_id": "Mohan", "target": "birthday", "thread_id": "<id>", "utterance": "Change the venue to The Oberoi" }
```
- Add/remove invitees
```json
{ "profile_id": "Mohan", "target": "birthday", "thread_id": "<id>", "utterance": "Add invitees c@example.com, d@example.com" }
```

Retrieve or save plan state
- GET `/api/nl/plan` with query `profile_id` and `thread_id`
- POST `/api/nl/plan/save` with `{ "thread_id": "<id>", "plan": { ... } }`

Notes
- When `target` is `auto`, birthday-related utterances are routed automatically.
- Invite preview gets updated when the template changes.

## 8) Streaming day plan (WebSocket)
Swagger doesn’t support WebSockets. To stream incremental cards:
- Connect to `ws://127.0.0.1:8000/ws/plan/day`
- Send: `{ "profile_id": "Ravindra", "date": "2025-08-19" }`
Use a WS client (Postman, wscat) to observe `card` and `done` messages.

## 9) Troubleshooting
- 404 Unknown profile_id → use `/api/profiles` or upsert a profile.
- Missing GOOGLE_API_KEY or LLM quota issues affect `/api/nl` flows.
- Date format: `YYYY-MM-DD` recommended.
- Timezone defaults to `Asia/Kolkata` unless set in the profile.

## 10) Schemas (for reference)
- PlanRequest: `{ profile_id: string, date?: string }`
- AgentRunRequest: `{ profile_id: string, agent: <enum>, context?: object }`
- BirthdayPlanRequest: `{ profile_id: string, spouse_name: string, event_date?: string, budget?: number, invitees?: string[] }`
- NaturalCommandRequest: `{ profile_id: string, target: "birthday"|"agent"|"auto", utterance: string, thread_id?: string, plan?: object, agent?: string }`
