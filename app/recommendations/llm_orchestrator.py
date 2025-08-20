from __future__ import annotations
from typing import Any, Dict, List, Tuple
from app.llm.llm import get_llm, _safe_text

MODEL_VERSION = "recs-2025-08-llm1"

THEME_SYSTEM = (
    "You are an event planner. Propose creative, feasible celebration themes for the given profile and event.\n"
    "- Use relationshipType, closenessScore, occasion, vibeGoal, headcount, budgetPerPerson, timeOfDay, dietaryConstraints, and location context.\n"
    "- If a child is involved (e.g., parent/child), avoid nightlife/alcohol/adult themes; prefer kid-friendly ideas (games, arcades, parks, science museum, comics).\n"
    "- Fit budget/headcount/timeOfDay/dietary constraints.\n"
    "Return strictly JSON with a 'themes' array; each theme must have id, title, description, rationale, tags, score."
)

RERANK_SYSTEM = (
    "You are a ranking model. Given profile+event constraints and venues, compute matchScore 0-1 and a 'why' rationale."
)

KID_KEYWORDS = {"kid", "kids", "child", "children", "family", "arcade", "game", "park", "museum", "science", "comics", "lego", "play"}
ADULT_EXCLUDE = {"bar", "nightlife", "club", "alcohol", "cocktail", "wine", "pub"}


def _fallback_themes() -> List[Dict[str, Any]]:
    return [
        {"id": "cozy_dinner", "title": "Cozy Chef's Tasting", "description": "Intimate tasting menu at a quiet spot.", "rationale": "Fits classy/cozy vibes.", "tags": ["cozy","classy"], "score": 0.72},
        {"id": "rooftop_evening", "title": "Rooftop Sunset", "description": "Golden-hour drinks with city views.", "rationale": "Great for photos and small groups.", "tags": ["scenic","lively"], "score": 0.68},
        {"id": "garden_brunch", "title": "Garden Brunch", "description": "Outdoor brunch with light live music.", "rationale": "Kid-friendly and relaxed.", "tags": ["outdoor","brunch"], "score": 0.65},
    ]


def _minor_context(event: Dict[str, Any]) -> bool:
    rel = (event.get("relationshipType") or "").lower()
    return any(tok in rel for tok in ["parent", "child", "son", "daughter", "kid"])


def _normalize_theme(t: Dict[str, Any]) -> Dict[str, Any]:
    tid = t.get("id") or t.get("title", "theme").lower().replace(" ", "_")
    tags = t.get("tags") or []
    # Ensure tags are lower-cased simple strings
    tags = [str(x).lower() for x in tags if isinstance(x, (str, int, float))]
    return {
        "id": tid,
        "title": t.get("title") or tid,
        "description": t.get("description") or "",
        "rationale": t.get("rationale"),
        "tags": tags,
        "score": t.get("score"),
    }


def _filter_kid_safe(themes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    safe: List[Dict[str, Any]] = []
    for t in themes:
        text = (t.get("title", "") + " " + t.get("description", "")).lower()
        tags = set(t.get("tags") or [])
        if any(a in text for a in ADULT_EXCLUDE) or (tags & ADULT_EXCLUDE):
            continue
        safe.append(t)
    return safe


def generate_themes(profile: Dict[str, Any], event: Dict[str, Any], n: int) -> List[Dict[str, Any]]:
    llm = get_llm()
    if not llm:
        return _fallback_themes()[:n]
    try:
        import json
        prompt = (
            THEME_SYSTEM
            + "\nProfile:" + json.dumps(profile)
            + "\nEvent:" + json.dumps(event)
            + f"\nReturn strictly JSON with key 'themes' (max {n})."
        )
        resp = llm.invoke(prompt)
        data = json.loads(_safe_text(resp) or "{}")
        themes = data.get("themes") or []
        if not isinstance(themes, list):
            return _fallback_themes()[:n]
        out: List[Dict[str, Any]] = [_normalize_theme(t) for t in themes[:n]]
        if _minor_context(event):
            out = _filter_kid_safe(out)
            # Optionally ensure kid-friendly bias when nothing remains
            if not out:
                out = [
                    {"id": "arcade_fun", "title": "Arcade and Games", "description": "Fun arcade session with tickets and prizes.", "rationale": "Kid-friendly and energetic.", "tags": ["arcade", "kid_friendly", "games"], "score": 0.7}
                ]
        return out if out else _fallback_themes()[:n]
    except Exception:
        return _fallback_themes()[:n]


def rerank_themes(themes: List[Dict[str, Any]], profile: Dict[str, Any], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    rel = (event.get("relationshipType") or "").lower()
    closeness = float(event.get("closenessScore") or 0.5)
    tod = (event.get("timeOfDay") or "").lower()
    head = int(event.get("headcount") or 2)
    budget = float(event.get("budgetPerPerson") or 0)

    def score_theme(t: Dict[str, Any]) -> float:
        s = float(t.get("score") or 0.5)
        tags = set(t.get("tags") or [])
        # Relationship signals
        if any(x in rel for x in ["parent", "child", "son", "daughter"]):
            if tags & {"kid_friendly", "family", "games", "arcade", "park", "museum"}:
                s += 0.2
            if tags & ADULT_EXCLUDE:
                s -= 0.5
        if "partner" in rel or "spouse" in rel:
            if tags & {"romantic", "intimate", "cozy"}:
                s += 0.15 * (0.5 + closeness)
        # Time of day
        if tod and tod in tags:
            s += 0.1
        if tod == "evening" and ("brunch" in tags):
            s -= 0.1
        # Headcount sizing (very rough)
        if head >= 8 and ("intimate" in tags):
            s -= 0.1
        if head <= 4 and ("large_group" in tags):
            s -= 0.1
        # Budget rough fit
        if budget:
            if budget <= 25 and ("budget_friendly" in tags or "casual" in tags):
                s += 0.1
            if budget >= 75 and ("premium" in tags or "classy" in tags):
                s += 0.1
        return s

    scored = [ (score_theme(t), t) for t in themes ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored]


def make_home_theme(event: Dict[str, Any]) -> Dict[str, Any]:
    rel = (event.get("relationshipType") or "").lower()
    who = "family" if any(x in rel for x in ["parent", "child", "son", "daughter"]) else "loved one"
    return {
        "id": "theme_home_quiet",
        "title": "Quiet at home",
        "description": "Relaxed time at home with simple activities and comfort food.",
        "rationale": f"Cozy bonding time tailored for {who}—board games, a favorite movie, and easy bites.",
        "tags": ["home", "quiet", "budget_friendly"],
        "score": 1.0,
    }


# Helpers for venue coupling

_TAG_QUERY_HINTS = [
    ("arcade", "arcade"),
    ("board game", "board game cafe"),
    ("kid_friendly", "family friendly"),
    ("museum", "science museum"),
    ("park", "park"),
    ("brunch", "brunch"),
    ("italian", "italian restaurant"),
    ("japanese", "sushi"),
    ("rooftop", "rooftop bar"),
    ("cozy", "cozy restaurant"),
]


def build_query_from_theme(theme: Dict[str, Any], event: Dict[str, Any]) -> str:
    tags = [str(t).lower() for t in (theme.get("tags") or [])]
    for key, q in _TAG_QUERY_HINTS:
        if any(key in t for t in tags):
            return q
    # Fallback to title keywords
    return theme.get("title", "restaurant")


def price_from_budget(budget_per_person: Any) -> int | None:
    try:
        b = float(budget_per_person)
    except Exception:
        return None
    if b < 20:
        return 1
    if b < 40:
        return 2
    if b < 80:
        return 3
    return 4


def rerank_venues(profile: Dict[str, Any], event: Dict[str, Any], theme: Dict[str, Any], venues: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    llm = get_llm()
    # Heuristic fallback when server LLM is disabled/unavailable
    if not llm:
        def h(v: Dict[str, Any]) -> float:
            rating = float(v.get("rating") or 0)
            price = v.get("price") or 2
            price_penalty = 0.1 * max(0, (price or 0) - 2)
            return max(0.0, min(1.0, (rating / 5.0) - price_penalty))
        scored = [{**v, "matchScore": h(v), "why": "Heuristic rating/price score."} for v in venues]
        scored.sort(key=lambda x: x.get("matchScore") or 0, reverse=True)
        return scored[:top_k]
    try:
        import json
        prompt = (
            RERANK_SYSTEM
            + "\nProfile:" + json.dumps(profile)
            + "\nEvent:" + json.dumps(event)
            + "\nTheme:" + json.dumps(theme)
            + "\nVenues:" + json.dumps(venues[:25])
            + f"\nReturn strictly JSON array of venues with added fields 'matchScore' (0-1) and 'why', limited to {top_k}. Preserve the 'id'."
        )
        resp = llm.invoke(prompt)
        arr = json.loads(_safe_text(resp) or "[]")
        if not isinstance(arr, list):
            raise ValueError("bad llm result")
        keep: List[Dict[str, Any]] = []
        for v in arr[:top_k]:
            keep.append({
                "id": v.get("id"),
                "name": v.get("name"),
                "address": v.get("address"),
                "coords": v.get("coords"),
                "price": v.get("price"),
                "rating": v.get("rating"),
                "photos": v.get("photos") or [],
                "url": v.get("url"),
                "bookingUrl": v.get("bookingUrl"),
                "why": v.get("why"),
                "matchScore": v.get("matchScore"),
                "source": v.get("source") or "mock",
            })
        return keep[:top_k]
    except Exception:
        sc = sorted(venues, key=lambda v: (v.get("rating") or 0), reverse=True)
        sc = [{**v, "matchScore": min(1.0, (v.get("rating") or 0)/5.0), "why": "Fallback by rating."} for v in sc]
        return sc[:top_k]
