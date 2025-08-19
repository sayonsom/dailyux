from app.schemas import AgentCard
from app.tools.content import spotify_recs, movie_recs


def run(profile, req):
    meta = profile.get("meta", {})
    ctx = req.get("context", {})
    taste = meta.get("music", "mix")
    role = (meta.get("role") or "").lower()
    load = ctx.get("day_load", "medium")

    family_mode = "exec" in role or "c-level" in role or "c level" in role
    picks = movie_recs("family" if family_mode else "trending")
    playlists = spotify_recs("relax", taste)

    suggestion = "Movie night at home" if family_mode else ("Catch up with friends" if meta.get("parties") else "Light dinner + show")
    if load == "heavy":
        suggestion = "Low-key unwind; short show + early night"

    return AgentCard(
        agent="LifeAfterWorkAgent",
        title="Evening Plans",
        summary=f"{suggestion}: Watch {picks[0]} · Music {playlists[0]}",
        priority=6,
        data={"movies": picks, "playlists": playlists, "suggestion": suggestion},
    )
