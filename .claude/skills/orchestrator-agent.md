# Skill: orchestrator-agent

## Description
Build or improve the calendar orchestrator in `orchestrator.py`. This is the Modal endpoint that handles multi-turn Slack conversations and routes calendar operations to Google Calendar API directly.

## Trigger
Use when building, modifying, or debugging orchestrator.py — intent classification, state management, multi-operation handling, or overall system architecture.

## Architecture

```
Slack → n8n HTTP Request → Modal handle_message (orchestrator.py)
                                     ↓
                           Load state from Modal Dict ({namn}-state)
                                     ↓
                           GPT-4.1 (intent + field extraction)
                           intents: create | update | delete | list | unclear | chat
                           max 5 operations per message
                                     ↓ (internal Python)
                           Google Calendar API (OAuth2)
                                     ↓
                           { reply: str } → n8n → Slack
```

n8n workflow: **Slack Trigger → HTTP Request → Slack Send**. Always one path — no IF node.

## Files
```
orchestrator.py          ← Modal endpoint (~320 lines)
lib/
  prompt.py              ← SYSTEM_PROMPT (all LLM rules live here)
  formatters.py          ← Swedish confirmations + state helpers
  calendar_client.py     ← Google Calendar API (OAuth2 + event lookup)
config.py                ← Auto-generated from clients/{namn}.py at deploy time
```

## Modal App Setup (per client)

```python
app = modal.App(config.MODAL_APP_NAME)   # e.g. "calendar-omar"
image = (
    modal.Image.debian_slim()
    .pip_install("openai", "fastapi", "google-auth", "google-auth-httplib2", "requests")
    .add_local_python_source("lib")
    .add_local_python_source("config")
)
orchestrator_state = modal.Dict.from_name(config.MODAL_DICT_NAME, create_if_missing=True)
# e.g. "omar-state"
```

## Modal Secrets (per client)
```python
_main_secrets = [
    modal.Secret.from_name(config.MODAL_SECRET_OPENAI),   # "openai-api-key"
    modal.Secret.from_name(config.MODAL_SECRET_AUTH),     # "api-auth-token-{namn}"
    modal.Secret.from_name(config.MODAL_SECRET_GOOGLE),   # "google-calendar-credentials-{namn}"
]
```

## Endpoint: handle_message

```
POST https://mmagenzy-info--calendar-{namn}-handle-message.modal.run
Authorization: Bearer {token}
Content-Type: application/json
Body: { "message": "...", "user_id": "..." }
Response: { "reply": "..." }
```

`min_containers=1` — always warm, no cold starts.

## LLM Call

```python
response = client.chat.completions.create(
    model="gpt-4.1",
    max_tokens=2048,
    response_format={"type": "json_schema", "json_schema": {...}},
    messages=[
        {"role": "system", "content": system},
        *conversation[-10:],           # last 10 messages for context
        {"role": "user", "content": message},
    ],
)
```

## LLM Output Schema

```json
{
  "operations": [
    {
      "intent": "create|update|delete|list|unclear|chat",
      "fields": {},
      "missing": ["field_name"],
      "reply": "Swedish question if info missing. Empty string if ready=true.",
      "ready": true,
      "awaiting_confirmation": false,
      "cancelled": false
    }
  ],
  "reply": "Top-level reply. Empty if all_ready=true. Required if all_ready=false.",
  "all_ready": true
}
```

## State Structure (Modal Dict, keyed by user_id)

```json
{
  "intent": "create|update|delete|null",
  "fields": {},
  "missing": [],
  "awaiting_confirmation": false,
  "event_history": [
    { "event_id": "abc123", "summary": "Tandläkare", "start": "2026-03-15T10:00:00" }
  ],
  "last_reply": "Tandläkare inbokat fredag 15/3 kl 10:00–11:00.",
  "conversation": [
    {"role": "user", "content": "boka tandläkare fredag 10-11"},
    {"role": "assistant", "content": "Tandläkare inbokat fredag 15/3 kl 10:00–11:00."}
  ],
  "pending_operations": []
}
```

- `event_history` — last 20 created events, used for update/delete lookup
- `conversation` — last 10 messages, sent to GPT-4.1 for context
- `last_reply` — latest confirmation, used to answer "har du bokat den?"
- `pending_operations` — multi-op state when some ops are waiting for more info

## Conversation Flow

1. Message arrives → load state → call GPT-4.1 with conversation history
2. `all_ready=false` → save state + conversation → return clarifying question to Slack
3. `cancelled=true` on an op → return "Okej, inget ändrat.", clear state
4. `all_ready=true` → execute all operations via Calendar API → Swedish confirmations → clear state

## _save() — internal state saver

```python
def _save(reply_text: str, new_state: dict, reset_conversation: bool = False) -> str:
    base = [] if reset_conversation else conversation
    new_conv = base + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply_text},
    ]
    new_state["conversation"] = new_conv[-10:]
    orchestrator_state[user_id] = new_state
    return reply_text
```

Note: function is named `_save`, not `_save_and_reply`.

## Google Credentials — fallback logic

```python
creds_data = json.loads(os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "{}"))
if not creds_data.get("refresh_token"):
    # Modal Secret is placeholder — read real credentials from admin_state
    admin_dict = modal.Dict.from_name("admin-state", create_if_missing=False)
    creds_data = admin_dict.get("clients", {}).get(config.CLIENT_NAME.lower(), {}).get("google_credentials", {})
```

## Deploy

```bash
PYTHONUTF8=1 modal deploy orchestrator.py
# OR (normal flow via GitHub Actions):
PYTHONUTF8=1 python deploy.py {namn}
```

## Evals

```
PASS: "tack" after successful booking
      → single chat operation, warm reply, event_history preserved

PASS: "har du bokat den?" (last_reply is set)
      → chat intent, reply references last_reply content

PASS: "14" (active intent=create, missing=[end_time])
      → intent=create, fields.end_time=14:00, does NOT switch to chat

PASS: full create flow → event_history grows by 1 entry
PASS: delete confirmed → event removed from event_history
PASS: "boka tandläkare fredag 14-15 och gympass måndag 10-11"
      → 2 create operations, both ready=true, both executed
PASS: any Calendar API error → Swedish error message, state not corrupted
```
