from pydantic import BaseModel, Field, AliasChoices
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

    # Optional client-supplied LLM results to use in place of server calls
    supervisor_insights_bullets: Optional[List[str]] = None

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
    # Accept numeric or free-form strings for budget; server will normalize
    budget: Optional[Union[int, str]] = 10000
    invitees: List[str] = Field(default_factory=list)

class UpsertProfileRequest(BaseModel):
    profile_id: str = Field(validation_alias=AliasChoices("profile_id", "profileId"))
    profile_json: Dict[str, Any]

# ---------------- Natural Language API ----------------

Tone = Literal["formal", "friendly", "playful", "romantic", "professional"]
Brevity = Literal["short", "medium", "detailed"]

class NaturalCommandRequest(BaseModel):
    profile_id: str
    target: Literal["birthday", "agent", "auto"] = "auto"
    utterance: str = ""
    thread_id: Optional[str] = None
    # Optional current state inputs for stateless edits
    plan: Optional[Dict[str, Any]] = None
    agent: Optional[str] = None  # when target==agent

    # Client-side NL interpretation result to avoid server LLM
    client_action: Optional[Dict[str, Any]] = None

class NaturalCommandResponse(BaseModel):
    ok: bool
    summary: str
    plan: Optional[Dict[str, Any]] = None
    cards: Optional[List[AgentCard]] = None
    thread_id: Optional[str] = None

# ---------------- Client-LLM Prompt APIs ----------------

class BuildPromptRequest(BaseModel):
    kind: Literal["supervisor_bullets", "interpret_nl"]
    prompt: Optional[str] = None
    utterance: Optional[str] = None

class BuildPromptResponse(BaseModel):
    prompt: str

# ---------------- Date/Time Update API ----------------

class DateTimeUpdateRequest(BaseModel):
    thread_id: str
    profile_id: str
    action: Literal["change_date", "refresh_times"]
    new_date: Optional[str] = None  # Only for change_date
    current_date: Optional[str] = None  # For validation or fallback

class DateTimeUpdateResponse(BaseModel):
    ok: bool = True
    message: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    thread_id: Optional[str] = None

# ---------------- v1: Recommendations API models ----------------

class ProfilePreferences(BaseModel):
    cuisinesLiked: List[str] = Field(default_factory=list)
    cuisinesAvoided: List[str] = Field(default_factory=list)
    dietaryRestrictions: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    favoriteVibes: List[str] = Field(default_factory=list)  # cozy, lively, classy
    noiseTolerance: Optional[str] = None  # low/med/high
    accessibilityNeeds: List[str] = Field(default_factory=list)
    alcoholPreference: Optional[str] = None
    kidFriendly: Optional[bool] = None

class ProfileBudget(BaseModel):
    typicalBudgetPerPerson: Optional[Union[str, float, int]] = None  # low/med/high or numeric

class ProfileInterests(BaseModel):
    hobbies: List[str] = Field(default_factory=list)
    musicGenres: List[str] = Field(default_factory=list)
    activitiesLiked: List[str] = Field(default_factory=list)
    indoorOutdoorPreference: Optional[str] = None

class ProfileHistoryItem(BaseModel):
    date: Optional[str] = None
    themeId: Optional[str] = None
    venueId: Optional[str] = None
    feedbackScore: Optional[float] = None

class ProfileConsent(BaseModel):
    shareDataWithLLM: Optional[bool] = None
    marketingConsent: Optional[bool] = None

class ProfileLLMHelpers(BaseModel):
    personaSummary: Optional[str] = None
    personaTags: List[str] = Field(default_factory=list)
    vectorEmbeddingId: Optional[str] = None

class Location(BaseModel):
    lat: Optional[float] = None
    lng: Optional[float] = None
    city: Optional[str] = None
    country: Optional[str] = None

class ProfileModel(BaseModel):
    profileId: str = Field(validation_alias=AliasChoices("profile_id", "profileId"))
    name: Optional[str] = None
    birthdate: Optional[str] = None
    pronouns: Optional[str] = None
    homeLocation: Optional[Location] = None
    timezone: Optional[str] = None

    preferences: Optional[ProfilePreferences] = None
    budget: Optional[ProfileBudget] = None
    interests: Optional[ProfileInterests] = None
    cultural: List[str] = Field(default_factory=list)  # religiousOrCulturalConstraints
    history: List[ProfileHistoryItem] = Field(default_factory=list)

    # The original JSON key is "defaultgemini-2.5" which is not a valid Python identifier.
    # Use a valid field name and map aliases so input/output still use the original key.
    defaultGemini_2_5: Optional[str] = Field(
        default=None,
        validation_alias="defaultgemini-2.5",
        serialization_alias="defaultgemini-2.5",
    )
    defaultClosenessScore: Optional[float] = None
    defaultGiftStyle: Optional[str] = None
    defaultSurpriseOk: Optional[bool] = None

    consent: Optional[ProfileConsent] = None
    llm: Optional[ProfileLLMHelpers] = None

class EventModel(BaseModel):
    eventId: Optional[str] = None
    profileId: str = Field(validation_alias=AliasChoices("profile_id", "profileId"))
    # Event context
    dateWindow: Optional[List[str]] = None  # [startISO, endISO]
    targetDate: Optional[str] = None
    headcount: Optional[int] = None
    occasion: Optional[str] = None  # birthday, milestone
    surprise: Optional[bool] = None
    indoorOutdoor: Optional[str] = None
    vibeGoal: List[str] = Field(default_factory=list)
    dietaryConstraints: List[str] = Field(default_factory=list)
    budgetPerPerson: Optional[Union[float, int]] = None
    radiusKm: Optional[float] = None
    cityOverride: Optional[str] = None
    timeOfDay: Optional[str] = None
    relationshipType: Optional[str] = None
    # Constraints
    mustInclude: List[str] = Field(default_factory=list)
    mustAvoid: List[str] = Field(default_factory=list)
    accessibility: List[str] = Field(default_factory=list)
    parkingNeeded: Optional[bool] = None
    publicTransitOk: Optional[bool] = None
    # Derived
    computedAgeAtEvent: Optional[int] = None
    localTime: Optional[str] = None
    closenessScore: Optional[float] = None
    giftStyle: Optional[str] = None
    surpriseOk: Optional[bool] = None

class Theme(BaseModel):
    id: str
    title: str
    description: str
    rationale: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    score: Optional[float] = None

class Coords(BaseModel):
    lat: float
    lng: float

class Venue(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    coords: Optional[Coords] = None
    price: Optional[Union[str, int]] = None
    rating: Optional[float] = None
    photos: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    bookingUrl: Optional[str] = None
    why: Optional[str] = None
    matchScore: Optional[float] = None
    source: Optional[str] = None  # google|yelp|mock

class RecommendationsRequest(BaseModel):
    topKThemes: int = 5
    topKVenues: int = 10
    forceRefresh: bool = False

class RecommendationsResponse(BaseModel):
    themes: List[Theme]
    venues: List[Venue]
    usedTools: List[str] = Field(default_factory=list)
    modelVersion: str
    ttlSeconds: int
    recId: Optional[str] = None

class CreateJobRequest(BaseModel):
    eventId: str
    topKThemes: int = 5
    topKVenues: int = 10
    forceRefresh: bool = False

class JobStatusResponse(BaseModel):
    jobId: str
    status: Literal["pending", "running", "complete", "failed"]
    result: Optional[RecommendationsResponse] = None
    error: Optional[str] = None

class FeedbackRequest(BaseModel):
    recId: Optional[str] = None
    thumbs: Literal["up", "down"]
    chosenItems: List[str] = Field(default_factory=list)  # theme or venue ids
    reasons: Optional[str] = None

class VenuesSearchRequest(BaseModel):
    query: Optional[str] = None
    lat: float
    lng: float
    radius: int = 3000  # meters
    cuisines: List[str] = Field(default_factory=list)
    priceLevel: Optional[int] = None  # 1-4 (google) or 1-4 (mapped)
    openAt: Optional[str] = None
    accessibility: List[str] = Field(default_factory=list)

# ---------------- Simulation / Timeline models ----------------

class TimelineTask(BaseModel):
    id: str
    kind: Literal[
        "decide_menu",
        "grocery_shopping",
        "wifi_access",
        "post_cleanup",
        "secure_locks",
    ]
    title: str
    scheduledAt: str  # ISO datetime
    dueAt: Optional[str] = None
    status: Literal["scheduled", "running", "done", "failed", "skipped"] = "scheduled"
    notes: Optional[str] = None
    result: Optional[Dict[str, Any]] = None

class SimTickRequest(BaseModel):
    thread_id: str
    now: Optional[str] = None  # ISO datetime; if omitted, server now()
    maxSteps: int = 10

class SimTickResponse(BaseModel):
    ok: bool
    thread_id: str
    now: str
    processed: List[TimelineTask] = Field(default_factory=list)
    remaining: int = 0

class SimStatusResponse(BaseModel):
    ok: bool
    thread_id: str
    now: Optional[str] = None
    tasks: List[TimelineTask] = Field(default_factory=list)

# ---------------- Organized REST: Birthday endpoints ----------------

class BirthdayStartRequest(BirthdayPlanRequest):
    pass

class BirthdayPlanResponse(BaseModel):
    thread_id: str
    plan: Dict[str, Any]

class ThemeUpdateRequest(BaseModel):
    theme: str

class VenueUpdateRequest(BaseModel):
    venue: str

class DateUpdateRequest(BaseModel):
    event_date: str

class TimeUpdateRequest(BaseModel):
    time: str

class BudgetUpdateRequest(BaseModel):
    budget: Union[int, str]

class InviteesPutRequest(BaseModel):
    invitees: List[str]

class InviteesEmailsRequest(BaseModel):
    emails: List[str]

class InvitesToneRequest(BaseModel):
    style: Tone
    brevity: Brevity

class InvitesTextRequest(BaseModel):
    template: str

# ---------------- Master Orchestrator ----------------

class OrchestrateRequest(BaseModel):
    profile_id: str
    honoree_name: Optional[str] = None  # pick from profile if missing
    relation: Optional[str] = None
    event_date: str
    venueMode: Literal["home", "restaurant", "auto"] = "auto"
    budget: Optional[Union[int, str]] = None
    invitees: List[str] = Field(default_factory=list)
    accelerateTo: Optional[str] = None  # ISO datetime to advance timeline

class OrchestrateResponse(BaseModel):
    ok: bool
    thread_id: str
    plan: Dict[str, Any]
    notes: Optional[str] = None
