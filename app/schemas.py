from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional, Union

class AgentCard(BaseModel):
    agent: str
    title: str
    summary: str
    priority: int = 5
    data: Dict[str, Any] = Field(default_factory=dict)

class PlanResponse(BaseModel):
    date: str
    profile_id: str
    timezone: str
    cards: List[AgentCard]
    rationale: str

class PlanRequest(BaseModel):
    profile_id: str
    date: Optional[str] = None

class AgentRunRequest(BaseModel):
    profile_id: str
    agent: Literal[
        "WorkLifeAgent","LifeAfterWorkAgent","RelaxationAgent",
        "FitnessAgent","TrafficAgent","GettingStartedAgent","HobbyAgent",
        "NutritionAgent","FinanceErrandsAgent","LearningAgent","CelebrationsAgent"
    ]
    context: Dict[str, Any] = Field(default_factory=dict)

class BirthdayPlanRequest(BaseModel):
    profile_id: str
    spouse_name: str = "Wife"
    event_date: Optional[str] = None
    budget: Optional[int] = 10000
    invitees: List[str] = Field(default_factory=list)

class UpsertProfileRequest(BaseModel):
    profile_id: str
    profile_json: Dict[str, Any]

# ---------------- Natural Language API ----------------

Tone = Literal["formal", "friendly", "playful", "romantic", "professional"]
Brevity = Literal["short", "medium", "detailed"]

class NaturalCommandRequest(BaseModel):
    profile_id: str
    target: Literal["birthday", "agent", "auto"] = "auto"
    utterance: str
    thread_id: Optional[str] = None
    # Optional current state inputs for stateless edits
    plan: Optional[Dict[str, Any]] = None
    agent: Optional[str] = None  # when target==agent

class NaturalCommandResponse(BaseModel):
    ok: bool
    summary: str
    plan: Optional[Dict[str, Any]] = None
    cards: Optional[List[AgentCard]] = None
    thread_id: Optional[str] = None
