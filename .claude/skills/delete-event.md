# Skill: delete-event

## Description
Rules and field definitions for the DELETE EVENT operation in the orchestrator. Use when modifying the delete flow in `orchestrator.py`.

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
  "question": "Är du säker på att du vill ta bort Tandläkare på fredag 15/1?"
}
```

**Turn 2a** — User says "ja":
```json
{
  "intent": "delete",
  "fields": { "event_identifier": { ... }, "confirmed": true },
  "ready": true,
  "awaiting_confirmation": false
}
```

**Turn 2b** — User says "nej":
```json
{
  "cancelled": true
}
```
→ Returns "Okej, inget ändrat."

## Event Lookup Strategy
Same as update-event:
1. Check `event_history` → keyword + date match
2. Fall back to Calendar API search
3. 0 found → ask user to be more specific
4. Multiple found → list options

## Google Calendar API — DELETE
`DELETE https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}`

Returns 204 No Content on success (no body).

```python
resp = http.delete(url, headers=_cal_headers())
# resp.content is empty — do NOT call resp.json()
```

## Swedish Confirmation Format
```
{summary} har tagits bort från kalendern.
```
Example: `"Tandläkare fredag 15/1 har tagits bort från kalendern."`

## After Success
Remove event from `event_history` by `event_id`.

## prompt.py
Delete rules (2-turn flow, confirmation keywords, cancelled handling) are implemented in `lib/prompt.py` under `=== STEP 2: COLLECT FIELDS — DELETE ===`.
**If you change any rule here, you MUST also update prompt.py.** The skills file describes intent; prompt.py is what actually runs.

## Evals
These cases must pass before and after any change to this skill or prompt.py:
```
PASS: "ta bort tandläkaren"
      → intent=delete, ready=false, awaiting_confirmation=true,
        reply asks for confirmation

PASS: "ja" (active intent=delete, awaiting_confirmation=true)
      → intent=delete, ready=true, fields.confirmed=true

PASS: "nej" (active intent=delete, awaiting_confirmation=true)
      → cancelled=true

PASS: "avbryt" (active intent=delete, awaiting_confirmation=true)
      → cancelled=true
```
