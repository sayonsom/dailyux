from typing import List, Dict

def fetch_emails() -> List[Dict]:
    return [
        {"from": "ceo@samsung.com", "subject": "Q4 Targets", "due": "today"},
        {"from": "hr@samsung.com", "subject": "Birthdays this week", "due": "tomorrow"},
    ]

def fetch_jira() -> List[Dict]:
    return [
        {"key": "ENG-101", "title": "Finalize OpenADR test plan", "status": "In Progress"},
        {"key": "ENG-203", "title": "Bug triage backlog", "status": "To Do"},
    ]
