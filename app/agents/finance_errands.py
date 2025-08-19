from app.schemas import AgentCard
from app.tools.work import fetch_emails


def run(profile, req):
    ctx = req.get("context", {})
    emails = fetch_emails()
    bills = [
        {"name": "Credit Card", "due": "in 2 days", "amount": 1200},
        {"name": "Electricity", "due": "in 5 days", "amount": 850},
    ]
    errands = [
        {"title": "Groceries (milk, eggs, greens)", "duration_min": 25},
        {"title": "Dry cleaning pickup", "duration_min": 15},
    ]

    # Slot a 30–45m errand block in the largest free block after 17:00, else any
    slot = None
    for b in sorted(ctx.get("free_blocks", []), key=lambda x: x.get("minutes", 0), reverse=True):
        if b.get("start", "00:00") >= "17:00" and b.get("minutes", 0) >= 30:
            slot = b; break
    slot = slot or (ctx.get("free_blocks", [None])[0])

    today_pay = [b for b in bills if b["due"] == "today"]
    summary = f"2 bills upcoming; {len(errands)} errands" + (f"; slot {slot['start']}" if slot else "")

    return AgentCard(
        agent="FinanceErrandsAgent",
        title="Finance & Errands",
        summary=summary,
        priority=5,
        data={
            "bills": bills,
            "emails_to_pay": [e for e in emails if "invoice" in e.get("subject", "").lower()],
            "errands": errands,
            "suggested_time": slot,
        },
    )
