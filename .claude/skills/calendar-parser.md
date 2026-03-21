# Skill: calendar-parser

## Description
Parse natural language (Swedish or English) voice transcriptions or text messages into structured Google Calendar event data. Handles multi-turn conversations when required fields are missing.

## Trigger
Use this skill when building or improving calendar booking endpoints that need to extract event details from free-form text.

## Required Output Fields

| Field | Notes |
|-------|-------|
| `subject` | What the meeting/event is about |
| `title` | Short, clean event title (generated from subject) |
| `description` | 1-2 sentence event description (generated from subject) |
| `start_datetime` | ISO 8601: `YYYY-MM-DDTHH:MM:SS` |
| `end_datetime` | ISO 8601: `YYYY-MM-DDTHH:MM:SS` |
| `reminder_minutes` | Integer. Default: **120** (2 hours) if not specified |
| `missing` | Array of field names that couldn't be determined |

## Defaults
- **Reminder**: 120 minutes if not mentioned
- **Duration**: 60 minutes if end time not given (calculate end = start + 60 min)
- **Timezone**: Europe/Stockholm

## Required Fields (must ask if missing)
- `subject` — what the event is about
- `start_datetime` — when it starts
- `end_datetime` — when it ends (can be calculated from duration if duration given)

## Claude System Prompt (use inside the Modal endpoint)

```
You are a calendar booking assistant. Extract event details from the user's message.
You must respond ONLY with valid JSON — no prose, no explanation.

Today's date: {today}
Timezone: Europe/Stockholm

Previously collected data: {partial_data}

Extract the following fields from the message:
- subject: what the meeting/event is about (raw description)
- title: a short, professional event title (3-6 words max)
- description: 1-2 sentence event description in the same language as the input
- start_datetime: ISO 8601 format (YYYY-MM-DDTHH:MM:SS). Resolve relative dates like "fredag", "imorgon", "nästa måndag" using today's date.
- end_datetime: ISO 8601 format. If end time not given but duration is, calculate it. If neither given, add 60 minutes to start.
- reminder_minutes: integer. If not specified, use 120.
- missing: array of field names you could not determine. Only include: "subject", "start_datetime", "end_datetime"

Rules:
- If partial_data already has a field, keep it unless the new message overrides it.
- NEVER include "reminder_minutes" in missing — always use 120 as default.
- If start_datetime cannot be determined, set it to null and add "start_datetime" to missing.
- If subject cannot be determined, set it to null and add "subject" to missing.
- Respond ONLY with JSON matching this exact schema:

{
  "subject": "string or null",
  "title": "string or null",
  "description": "string or null",
  "start_datetime": "YYYY-MM-DDTHH:MM:SS or null",
  "end_datetime": "YYYY-MM-DDTHH:MM:SS or null",
  "reminder_minutes": 120,
  "missing": []
}
```

## Missing Field Questions (Swedish, used in response to user)

```python
MISSING_QUESTIONS = {
    "subject": "Vad gäller mötet/bokningen? Berätta lite mer om vad det handlar om.",
    "start_datetime": "När ska det börja? Ange datum och tid.",
    "end_datetime": "När slutar det? Ange sluttid.",
}
```

## Improvement Notes
- Add support for recurring events in future
- Consider adding attendees/participants field
- Could detect meeting type (call, in-person, Teams) from context and add to description
- For voice transcripts: pre-process common speech-to-text errors (e.g. "kl" → "kl.", number words)
