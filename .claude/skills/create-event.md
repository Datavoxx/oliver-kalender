# Skill: create-event

## Description
Rules and field definitions for the CREATE EVENT operation in the orchestrator. Use when modifying the create flow in `orchestrator.py` or create rules in `lib/prompt.py`.

## Trigger
Use when building or debugging calendar event creation — field extraction, confirmation format, or the Calendar API POST call.

## Required Fields (max 2 questions to user)
| Field | Notes |
|-------|-------|
| `subject` | What the event is about, in user's own words. Derives `title` + `description`. |
| `date` | Which day — stored as `YYYY-MM-DD`. Resolve relative Swedish dates. |
| `start_time` | Start time — `HH:MM` |
| `end_time` | End time — `HH:MM`. Calculate from duration if given. |

When date + start_time known → set `start_datetime = date + "T" + start_time + ":00"`
When date + end_time known → set `end_datetime = date + "T" + end_time + ":00"`

**MIDNIGHT RULE:** If end_time is "00:00" and start_time >= 20:00 → end_date = start_date + 1 day.
Python safety in orchestrator.py also handles this: if `end_datetime <= start_datetime`, adds timedelta(days=1).

**TIME FORMAT RULE:** Times may be written as HH:MM, HH.MM, or HH,MM — all mean the same. "10,20" = "10.20" = "10:20". Always normalize to HH:MM.

## Auto-derived Fields (never ask)
| Field | Notes |
|-------|-------|
| `title` | Short 3-6 word professional version of subject |
| `description` | 2-3 full sentences of context from subject. Phone/email always at top: "📞 [number]\n\n" |

## Optional Fields (use only if user mentions)
| Field | Default | Notes |
|-------|---------|-------|
| `reminder_minutes` | **30** | NEVER ask. Capture only if user explicitly says e.g. "påminn 2 timmar innan" → 120. Default is 30 min. |
| `location` | null | |
| `attendees` | [] | List of email strings |
| `recurrence` | null | Full RRULE string — set automatically if user mentions recurring pattern |

## Missing Field Questions (Swedish)
```
subject missing:               "Vad handlar eventet om?"
date/start_time/end_time:      "Vilket datum och vilken tid? (t.ex. 14/4 kl 10–12)"
```
date, start_time, end_time are ALWAYS asked together in ONE question if any are missing.

## Google Calendar API Body
```python
event_body = {
    "summary": fields.get("title") or fields.get("summary"),
    "description": fields.get("description", ""),
    "start": {"dateTime": fields["start_datetime"], "timeZone": config.TIMEZONE},
    "end":   {"dateTime": fields["end_datetime"],   "timeZone": config.TIMEZONE},
    "reminders": {
        "useDefault": False,
        "overrides": [
            {"method": "popup", "minutes": fields.get("reminder_minutes", 30)},
            {"method": "email", "minutes": 60},
        ],
    },
}
# Optional additions:
if fields.get("location"):   event_body["location"] = fields["location"]
if fields.get("attendees"):  event_body["attendees"] = [{"email": e} for e in fields["attendees"]]
if fields.get("recurrence"): event_body["recurrence"] = [fields["recurrence"]]
```

## Recurrence (RRULE)

If user says "varje [dag/vecka/weekday]" → LLM sets `fields.recurrence` as a full RRULE string. No end date unless user specifies.

| Swedish phrase | RRULE |
|---|---|
| "varje dag" / "dagligen" | `RRULE:FREQ=DAILY` |
| "varje vecka" | `RRULE:FREQ=WEEKLY` |
| "varje måndag" | `RRULE:FREQ=WEEKLY;BYDAY=MO` |
| "varje fredag" | `RRULE:FREQ=WEEKLY;BYDAY=FR` |
| "varje måndag och fredag" | `RRULE:FREQ=WEEKLY;BYDAY=MO,FR` |
| "varje vardag" / "varje arbetsdag" | `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR` |
| "varje månad" | `RRULE:FREQ=MONTHLY` |
| "varje år" | `RRULE:FREQ=YEARLY` |
| + "i 4 veckor" | append `;COUNT=4` |
| + "till 1 juni" | append `;UNTIL=20260601` |

`date` = first occurrence. orchestrator.py adds `event_body["recurrence"] = [fields["recurrence"]]`.

## API Endpoint
`POST https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`

## Swedish Confirmation Format (lib/formatters.py)
```
{title} inbokat {weekday} {day}/{month} kl {HH:MM}–{HH:MM}. Påminnelse {X minuter/timmar} innan.
```
Example: `"Tandläkare inbokat fredag 15/3 kl 14:00–15:00. Påminnelse 30 minuter innan."`

Recurring:
```
{title} inbokat {recurrence_sv} kl {HH:MM}–{HH:MM} (första gången {weekday} {day}/{month}). Påminnelse {X} innan.
```

## After Success
Save to `event_history` in state:
```python
{ "event_id": result["id"], "summary": result["summary"], "start": fields["start_datetime"] }
```
Keep last 20 entries.

## prompt.py
All create rules (required fields, MIDNIGHT RULE, TIME FORMAT RULE, reminder default=30, question wording) are implemented in `lib/prompt.py` under `** CREATE **`.
**If you change any rule here, you MUST also update prompt.py.** The skill describes intent; prompt.py is what actually runs.

## Evals
```
PASS: "boka tandläkare fredag 14-15"
      → intent=create, ready=true, fields.start_time=14:00, fields.end_time=15:00

PASS: "boka något imorgon"
      → intent=create, ready=false, reply asks "Vad handlar eventet om?"

PASS: "boka tandläkare" (no time given)
      → intent=create, ready=false, reply asks date+time in ONE combined question

PASS: "23" (active intent=create, missing=[end_time])
      → intent=create, fields.end_time=23:00, does NOT switch to intent=chat

PASS: "möte med Anna fredag 22:00-00:00"
      → MIDNIGHT RULE: end_datetime = next day 00:00, NOT same day

PASS: "gympass fredag 18:00 i en timme"
      → intent=create, fields.end_time=19:00 (duration calculated)

PASS: "boka ett event" (generic phrase, no subject)
      → intent=create, ready=false, reply asks "Vad handlar eventet om?"

PASS: "boka tandläkare fredag 14-15 och gympass måndag 10-11"
      → 2 create operations, all_ready=true, both executed
```
