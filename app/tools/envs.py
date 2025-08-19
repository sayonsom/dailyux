from typing import Dict

def weather(location: str, date: str) -> Dict:
    return {"location": location, "date": date, "high": 31, "low": 24, "condition": "Partly Cloudy"}

def route(origin: str, dest: str, when: str) -> Dict:
    return {"origin": origin, "dest": dest, "eta_min": 42, "route": ["ORR", "Exit 9", "Service Rd"]}
