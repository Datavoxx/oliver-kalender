# Skill: delete-event

## Description
Rules and field definitions for the DELETE EVENT operation in the orchestrator. Use when modifying the delete flow in `orchestrator.py` or delete rules in `lib/prompt.py`.

## Trigger
Use when building or debugging event deletion — event lookup, confirmation flow, or the Calendar API DELETE call.

## Conversation Flow (2-turn)

**Turn 1** — User says "ta bort tandläkaren":
```json
{
  "intent": "delete",
  "fields": { "event_identifier": { "keywords": ["tandläkare"], "date": null }, "confirmed": false },
  "ready": false,
  "awaiting_confirmation": true,
  "reply": "Är du säker på att du vill ta bort Tandläkare på fredag 15/3?"
}
```

**Turn 2a** — User says "ja":
```json
{
  "intent": "delete",
  "fields": { "event_identifier": { ... }, "confirmed": true },
  "ready": true,
  "awaiting_confirmation": false,
  "reply": ""
}
```

**Turn 2b** — User says "nej" or "avbryt":
```json
{
  "intent": "delete",
  "cancelled": true,
  "reply": ""
}
```
→ orchestrator returns "Okej, inget ändrat." and clears state.

Note: The confirmation question is in the `"reply"` field (not `"question"`).

## Event Lookup Strategy
Same as update-event:
1. Check `event_history` in state — keyword + date match (case-insensitive substring)
2. If no history match → `GET /calendars/{id}/events?q={keywords}&timeMin=now`
3. Exactly 1 result → proceed with delete confirmation
4. 0 results → "Hittade inget matchande event att ta bort. Kan du vara mer specifik?"
5. Multiple → list options, ask user to specify

## Google Calendar API — DELETE
`DELETE https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}`

Returns 204 No Content on success (no body).

```python
cal.request("DELETE", f"{cal.base_url}/{found['event_id']}")
# cal.request() handles empty response: returns {} if resp.content is empty
```

## Swedish Confirmation Format (lib/formatters.py)
```
{summary} har tagits bort från kalendern.
```
Example: `"Tandläkare fredag 15/3 har tagits bort från kalendern."`

## After Success
Remove event from `event_history` by `event_id`:
```python
new_history = remove_from_history(new_history, found["event_id"])
```

## prompt.py
Delete rules (2-turn flow, awaiting_confirmation logic, cancelled handling) are implemented in `lib/prompt.py` under `** DELETE **`.
**If you change any rule here, you MUST also update prompt.py.** The skill describes intent; prompt.py is what actually runs.

## Evals
```
PASS: "ta bort tandläkaren"
      → intent=delete, ready=false, awaiting_confirmation=true,
        reply (not "question") asks for confirmation

PASS: "ja" (active intent=delete, awaiting_confirmation=true)
      → intent=delete, ready=true, fields.confirmed=true

PASS: "nej" (active intent=delete, awaiting_confirmation=true)
      → cancelled=true

PASS: "avbryt" (active intent=delete, awaiting_confirmation=true)
      → cancelled=true
```
