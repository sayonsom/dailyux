from typing import List

def spotify_recs(mood: str, genre: str) -> List[str]:
    base = [f"{genre.title()} Mix #{i}" for i in range(1, 5)]
    if mood == "focus": base.append("Deep Work Instrumentals")
    if mood == "relax": base.append("Evening Chillout")
    return base

def movie_recs(taste: str) -> List[str]:
    return [f"Top pick for {taste}", "Critically Acclaimed 2025", "Trending on OTT"]
