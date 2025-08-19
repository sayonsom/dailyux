from app.schemas import AgentCard
from app.tools.work import fetch_emails, fetch_jira

def run(profile, req):
    ctx = req.get("context", {})
    is_weekend = bool(ctx.get("is_weekend"))
    emails = fetch_emails(); jira = fetch_jira(); bdays = ["Teammate A (today)", "Teammate B (Fri)"]

    if is_weekend:
        # Weekend: soften work focus to weekly review & planning
        summary = "Weekend review: inbox triage + plan next week"
        data = {
            "weekly_review": [
                "Scan inbox for high-signal threads",
                "Review calendar next week",
                "Pick top 3 goals",
            ],
            "emails": emails,
            "jira": jira,
        }
        return AgentCard(agent="WorkLifeAgent", title="Weekend Planning", summary=summary, priority=6, data=data)

    # Weekday path
    urgent_emails = [e for e in emails if e.get("due") == "today"]
    top_jira = [j for j in jira if j.get("status") != "Done"][:2]

    load = ctx.get("day_load", "medium")
    focus_plan = {
        "light": ["Ship one backlog ticket", "Inbox zero"],
        "medium": ["Advance ENG-101", "Reply to 3 key threads"],
        "heavy": ["Unblock ENG-101", "Defer noncritical emails"],
    }.get(load, ["Advance key task", "Reply to 3 threads"])

    summary = f"{len(emails)} emails, {len(jira)} Jira; today: {len(urgent_emails)} urgent; birthdays: {bdays[0]}…"
    data = {
        "emails": emails,
        "urgent_emails": urgent_emails,
        "jira": jira,
        "top_jira": top_jira,
        "birthdays": bdays,
        "focus_plan": focus_plan,
    }
    return AgentCard(agent="WorkLifeAgent", title="Work Focus", summary=summary, priority=3, data=data)
