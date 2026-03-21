# Skill: update-event

## Description
Rules and field definitions for the UPDATE EVENT operation in the orchestrator. Use when modifying the update flow in `orchestrator.py`.

## Trigger
Use when building or debugging event updates — event lookup, partial PATCH logic, or confirmation format.

## LLM Extracts

### event_identifier
```json
{
  "keywords": ["tandläkare", "läkare"],
  "date": "2024-01-15"
}
```
- `keywords`: 1-3 words from how the user described the event
- `date`: `YYYY-MM-DD` if user specifies a date, otherwise null

### changes
Only include fields the user explicitly wants to change:
```json
{
  "start_datetime": "2024-01-18T10:00:00",
  "end_datetime":   "2024-01-18T11:00:00",
  "summary":        "New title",
  "description":    "Updated description",
  "location":       "Storgatan 1",
  "reminder_minutes": 30
}
```

## Event Lookup Strategy
1. Check `event_history` in state — match by keywords (case-insensitive substring) and optional date
2. If no history match → `GET /calendars/{id}/events?q={keywords}&timeMin=now`
3. Exactly 1 result → proceed with update
4. 0 results → "Hittade inget matchande event. Kan du vara mer specifik?"
5. Multiple → list options, ask user to specify

## Google Calendar API — PATCH (partial update)
`PATCH https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}`

Only send fields that are being changed:
```python
patch_body = {}
if "summary"         in changes: patch_body["summary"] = changes["summary"]
if "start_datetime"  in changes: patch_body["start"] = {"dateTime": changes["start_datetime"], "timeZone": "Europe/Stockholm"}
if "end_datetime"    in changes: patch_body["end"]   = {"dateTime": changes["end_datetime"],   "timeZone": "Europe/Stockholm"}
if "description"     in changes: patch_body["description"] = changes["description"]
if "location"        in changes: patch_body["location"] = changes["location"]
if "reminder_minutes" in changes:
    patch_body["reminders"] = {
        "useDefault": False,
        "overrides": [{"method": "popup", "minutes": changes["reminder_minutes"]}]
    }
```

## Swedish Confirmation Format
```
{original_summary} är uppdaterat. Ny tid: {weekday} {day}/{month} kl {HH:MM}.
```
Example: `"Tandläkare är uppdaterat. Ny tid: måndag 18/1 kl 10:00."`

## After Success
Update `event_history`: replace old entry with updated summary/start.

## prompt.py
Update rules (event_identifier, changes structure) are implemented in `lib/prompt.py` under `=== STEP 2: COLLECT FIELDS — UPDATE ===`.
**If you change any rule here, you MUST also update prompt.py.** The skills file describes intent; prompt.py is what actually runs.

## Evals
These cases must pass before and after any change to this skill or prompt.py:
```
PASS: "flytta tandläkaren till måndag 10-11"
      → intent=update, event_identifier.keywords includes "tandläkare",
        changes has start_datetime + end_datetime

PASS: "ändra titeln på mötet fredag till Projektmöte"
      → intent=update, changes.summary="Projektmöte"

PASS: "flytta mötet" (no new time specified)
      → intent=update, ready=false, asks what to change

PASS: "hej" (active intent=update in progress)
      → intent=chat, state reset
```
