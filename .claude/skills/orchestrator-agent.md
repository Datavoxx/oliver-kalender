# Skill: orchestrator-agent

## Description
Build or improve the calendar orchestrator agent in `orchestrator.py`. This is the main Modal endpoint that manages multi-turn Slack conversations and routes calendar operations to Google Calendar API directly.

## Trigger
Use when building, modifying, or debugging the orchestrator — intent classification, state management, conversation flow, or the overall system architecture.

## Architecture

```
Slack → n8n HTTP Request → Modal handle_message (orchestrator)
                                     ↓
                           OpenAI gpt-4.1 (intent + field extraction)
                           intents: create | update | delete | list | unclear | chat
                                     ↓ (internal Python functions)
                           Google Calendar API (OAuth2)
                           - create/update/delete: modifies events, returns htmlLink
                           - list: fetches ALL events for a date
                                     ↓
                           { reply: str } → n8n → Slack
```

n8n workflow: **Slack Trigger → HTTP Request → Slack Send**. Always one path — no IF node.

## Files
```
orchestrator.py          ← Modal endpoint (~175 lines)
lib/
  __init__.py
  prompt.py              ← SYSTEM_PROMPT
  formatters.py          ← Swedish confirmations + state helpers
  calendar_client.py     ← Google Calendar API (OAuth2 + event lookup)
```

## Modal App Setup

```python
app = modal.App("calendar-orchestrator")
image = (
    modal.Image.debian_slim()
    .pip_install("openai", "fastapi", "google-auth", "google-auth-httplib2", "requests")
    .add_local_python_source("lib")
)
orchestrator_state = modal.Dict.from_name("orchestrator-state", create_if_missing=True)
```

## Modal Secrets Required
- `openai-api-key` → `OPENAI_API_KEY`
- `api-auth-token` → `API_AUTH_TOKEN`
- `google-calendar-credentials` → `GOOGLE_CALENDAR_CREDENTIALS` (JSON string)

## google-calendar-credentials JSON structure
```json
{
  "refresh_token": "1//...",
  "client_id": "415390219435-....apps.googleusercontent.com",
  "client_secret": "GOCSPX-...",
  "calendar_id": "primary"
}
```

## State Structure (Modal Dict: `orchestrator-state`, keyed by user_id)
```json
{
  "intent": "create|update|delete|null",
  "fields": {},
  "missing": [],
  "awaiting_confirmation": false,
  "last_reply": "Tandläkare inbokat fredag 15/1 kl 14:00–15:00.",
  "event_history": [
    { "event_id": "abc123", "summary": "Tandläkare", "start": "2024-01-15T10:00:00" }
  ],
  "conversation": [
    {"role": "user", "content": "boka tandläkare fredag 14-15"},
    {"role": "assistant", "content": "Tandläkare inbokat fredag 15/1 kl 14:00–15:00."}
  ]
}
```
- `event_history` — last 20 events, used for update/delete lookup
- `conversation` — last 10 messages (5 pairs), sent to OpenAI for context
- `last_reply` — latest confirmation, used to answer follow-up questions

## LLM Call
```python
response = client.chat.completions.create(
    model="gpt-4.1",
    max_tokens=1024,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": system},
        *conversation[-10:],
        {"role": "user", "content": message},
    ],
)
```

## LLM Output Schema
```json
{
  "intent": "create|update|delete|list|unclear|chat",
  "fields": {},
  "missing": ["field_name"],
  "reply": "Swedish reply or empty string if ready=true",
  "ready": false,
  "awaiting_confirmation": false,
  "cancelled": false
}
```

## Conversation Flow
1. Message arrives → load state → call LLM with conversation history
2. `ready=false` → save state + conversation → return question to Slack
3. `cancelled=true` → clear state → return "Okej, inget ändrat."
4. `ready=true` → execute Calendar API → save last_reply → return Swedish confirmation

## Deploy
```bash
PYTHONUTF8=1 modal deploy orchestrator.py
```

## Evals
These cross-cutting cases must pass after any change to orchestrator.py or prompt.py:
```
PASS: "tack" after successful booking
      → intent=chat, warm reply, event_history preserved (NOT cleared)

PASS: "har du bokat den?" (last_reply is set)
      → intent=chat, reply references the last operation result

PASS: "14" (active intent=create, missing=[start_time])
      → intent=create, fields.start_time=14:00, does NOT switch to chat

PASS: full create flow → event_history grows by 1 entry
PASS: delete confirmed → event removed from event_history
PASS: any API error → Swedish error message returned, state not corrupted
```

Run prompt evals: `OPENAI_API_KEY=xxx python evals/test_prompt.py`
