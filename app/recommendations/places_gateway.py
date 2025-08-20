from __future__ import annotations
from typing import Any, Dict, List, Optional
import hashlib, json, time
import requests
from app.settings import settings

# Minimal in-memory cache; replace with Redis in production
_PLACES_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 6 * 60 * 60
_GOOGLE_PLACES_URLS = {
    "text": "https://maps.googleapis.com/maps/api/place/textsearch/json",
    "nearby": "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
    "photo": "https://maps.googleapis.com/maps/api/place/photo",
}


def _cache_key(params: Dict[str, Any]) -> str:
    s = json.dumps(params, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()


def _now() -> float:
    return time.time()


def _get_cached(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    k = _cache_key(params)
    item = _PLACES_CACHE.get(k)
    if not item:
        return None
    if _now() - item.get("ts", 0) > _CACHE_TTL_SECONDS:
        _PLACES_CACHE.pop(k, None)
        return None
    return item


def _set_cached(params: Dict[str, Any], data: Dict[str, Any]) -> None:
    k = _cache_key(params)
    _PLACES_CACHE[k] = {"ts": _now(), "data": data}


# ---------------- Google Places adapter ----------------

def _build_photo_url(photo_ref: str, maxwidth: int = 800) -> str:
    key = settings.maps_key()
    if not key:
        return ""
    return f"{_GOOGLE_PLACES_URLS['photo']}?maxwidth={maxwidth}&photo_reference={photo_ref}&key={key}"


def _google_places(params: Dict[str, Any]) -> Dict[str, Any]:
    key = settings.maps_key()
    if not key:
        raise RuntimeError("Missing Google Maps API key")

    lat = params.get("lat"); lng = params.get("lng")
    query = params.get("query")
    cuisine = params.get("cuisine")
    radius = int(params.get("radius") or 3000)
    price_level = params.get("priceLevel")

    session = requests.Session()
    common = {"key": key}

    # Prefer Text Search when query is given, else Nearby Search
    if query:
        q = query
        if cuisine and cuisine.lower() not in q.lower():
            q = f"{cuisine} {q}"
        payload = {**common, "query": q, "location": f"{lat},{lng}", "radius": radius}
        if price_level is not None:
            # minprice/maxprice 0-4 in Places; map our 1-4 to 0-4 conservatively
            try:
                p = int(price_level)
                payload["maxprice"] = max(0, min(4, p))
            except Exception:
                pass
        url = _GOOGLE_PLACES_URLS["text"]
    else:
        payload = {**common, "location": f"{lat},{lng}", "radius": radius, "type": "restaurant"}
        if cuisine:
            payload["keyword"] = cuisine
        if price_level is not None:
            try:
                p = int(price_level)
                payload["maxprice"] = max(0, min(4, p))
            except Exception:
                pass
        url = _GOOGLE_PLACES_URLS["nearby"]

    # Single page only (up to 20 results) to keep cost predictable
    resp = session.get(url, params=payload, timeout=8)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    out: List[Dict[str, Any]] = []
    for r in results:
        photos = []
        for ph in r.get("photos", [])[:3]:
            ref = ph.get("photo_reference")
            if ref:
                photos.append(_build_photo_url(ref))
        out.append({
            "id": r.get("place_id"),
            "name": r.get("name"),
            "address": r.get("formatted_address") or r.get("vicinity"),
            "coords": {"lat": r.get("geometry", {}).get("location", {}).get("lat"), "lng": r.get("geometry", {}).get("location", {}).get("lng")},
            "price": r.get("price_level"),
            "rating": r.get("rating"),
            "photos": photos,
            "url": f"https://www.google.com/maps/place/?q=place_id:{r.get('place_id')}",
            "bookingUrl": None,
            "source": "google",
        })
    return {"provider": "google", "results": out}


# ---------------- Fallback mock provider ----------------

def _mock_google_places(params: Dict[str, Any]) -> Dict[str, Any]:
    lat = params.get("lat"); lng = params.get("lng")
    q = params.get("query") or "restaurant"
    return {
        "provider": "mock",
        "results": [
            {
                "id": f"g_{int((lat or 0)*1000)}_{int((lng or 0)*1000)}_{i}",
                "name": f"{q.title()} Place {i}",
                "address": "123 Example St",
                "coords": {"lat": lat, "lng": lng},
                "price": i % 4 + 1,
                "rating": 4.2 - (i * 0.1),
                "photos": [],
                "url": "https://maps.google.com/?q=Example",
                "bookingUrl": None,
                "source": "mock",
            }
            for i in range(1, 12)
        ],
    }


# ---------------- Public API ----------------

def search_places(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Attempt cache
    cached = _get_cached(params)
    if cached:
        return cached["data"].get("results", [])

    try:
        if settings.maps_key():
            data = _google_places(params)
        else:
            data = _mock_google_places(params)
    except Exception:
        data = _mock_google_places(params)

    _set_cached(params, data)
    return data.get("results", [])
