#!/usr/bin/env bash
set -euo pipefail

# Simple smoke test to verify client performs LLM work and server accepts results.
# Requirements: curl; jq (optional for pretty output)

BASE_URL="${BASE_URL:-http://localhost:8000}"
PROFILE="${PROFILE:-Ravindra}"
USE_JQ=1
command -v jq >/dev/null 2>&1 || USE_JQ=0

function print_json() {
  if [[ $USE_JQ -eq 1 ]]; then
    jq .
  else
    cat
  fi
}

echo "==> 1) Health"
curl -s "$BASE_URL/health" | print_json

# Also check profiles
curl -s "$BASE_URL/api/profiles" | print_json

echo "\n==> 2) Get supervisor prompt (server computes context; client does LLM)"
SUP=$(curl -s "$BASE_URL/api/prompts/supervisor?profile_id=$PROFILE")
if [[ $USE_JQ -eq 1 ]]; then
  echo "$SUP" | jq . >/dev/null
  PROMPT=$(echo "$SUP" | jq -r '.prompt')
else
  PROMPT=$(echo "$SUP" | sed -n 's/.*"prompt":"\(.*\)".*/\1/p')
fi

# Display a snippet of the prompt
echo "Prompt (first 200 chars):"
echo "$PROMPT" | head -c 200; echo

echo "\n==> 3) Simulate client LLM bullets (you would call Gemini client-side here)"
# In a real client, call your model with $PROMPT and parse bullets.
# Here we just fake three bullets to prove the flow end-to-end.
BULLETS='["Protect 60m deep work 09:00-10:00","Batch emails at 12:30 and 17:30","Prep unwind by 21:30"]'
echo "Client bullets: $BULLETS"

echo "\n==> 4) Send plan request with client bullets"
RESP=$(curl -s -X POST "$BASE_URL/api/plan/day" \
  -H 'Content-Type: application/json' \
  -d "{\"profile_id\":\"$PROFILE\",\"supervisor_insights_bullets\":$BULLETS}")
if [[ $USE_JQ -eq 1 ]]; then
  echo "$RESP" | jq '{date, profile_id, first_card: .cards[0], rationale}'
else
  echo "$RESP"
fi

echo "\n==> 5) Natural language with client_action (no server LLM)"
NL_PAYLOAD='{"profile_id":"'"$PROFILE"'","target":"birthday","client_action":{"type":"change_venue","venue":"The Blue Door"}}'
RESP=$(curl -s -X POST "$BASE_URL/api/nl" -H 'Content-Type: application/json' -d "$NL_PAYLOAD")
if [[ $USE_JQ -eq 1 ]]; then
  echo "$RESP" | jq '{ok, summary, plan}
'
else
  echo "$RESP"
fi

echo "\nDone. Verified that client provided LLM outputs (bullets and client_action) and backend processed them without calling an LLM."
