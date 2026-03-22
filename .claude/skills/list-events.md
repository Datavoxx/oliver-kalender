# Skill: list-events

## Description
List all calendar events for a specific date. Used when user asks what they have booked on a given day.

## Trigger
Use when building, modifying, or debugging the "list" intent — fetching all events for a date from Google Calendar and formatting the response.

## Intent Classification
Prompt triggers `intent="list"` for messages like:
- "vad har jag imorgon?"
- "vad är inbokat på fredag?"
- "har jag något idag?"
- "vad händer på lördag?"

Required field: `date` (YYYY-MM-DD). Resolved from relative expressions using today's date.

## Flow

```
User: "vad har jag imorgon?"
  → LLM: intent=list, fields={date: "2026-03-23"}, ready=true
  → orchestrator: cal.list_events("2026-03-23")
  → Calendar API: GET /calendars/primary/events?timeMin=...&timeMax=...
  → format_events_list(events, date_str)
  → reply: "Du har 3 bokningar måndag 23/3:\n• 10:00–12:00 — Möte med Oliver\n..."
```

## CalendarClient.list_events (lib/calendar_client.py)

```python
def list_events(self, date_str: str) -> list:
    tz = _tz_offset()   # e.g. "+01:00" or "+02:00" depending on DST
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": f"{date_str}T00:00:00{tz}",
        "timeMax": f"{date_str}T23:59:59{tz}",
        "maxResults": 20,
    }
    result = self.request("GET", self.base_url, params=params)
    return result.get("items", [])
```

Note: Uses `_tz_offset()` to get the correct UTC offset for Europe/Stockholm (handles DST automatically).

## format_events_list (lib/formatters.py)

```python
def format_events_list(events: list, date_str: str) -> str:
    # Empty → "Du har inga bokningar {dag} {datum}."
    # With events → "Du har N bokningar {dag} {datum}:\n• HH:MM–HH:MM — Titel\n..."
    # All-day events (no dateTime) show the date string as time (effectively "heldag")
```

## Orchestrator branch (orchestrator.py)

```python
elif intent == "list":
    date_str = fields.get("date")
    if not date_str:
        confirmations.append("Vilket datum vill du kolla?")
        continue
    events = cal.list_events(date_str)
    confirmations.append(format_events_list(events, date_str))
```

State is reset after list (same as other completed operations via `_save()`).

## Prompt rules (lib/prompt.py)

```
** LIST **
Required: date (YYYY-MM-DD). Resolve relative dates using today: {today}.
If no date is given, ask: "Vilket datum vill du kolla?"
Set ready=true as soon as date is known. fields: {"date": "YYYY-MM-DD"}
```

## Notes
- Uses Calendar API directly — sees ALL events, not just those created by the bot
- Does NOT modify event_history
- maxResults=20 prevents oversized responses
- Can be combined with create in one message: "vad har jag imorgon och boka yoga torsdag 18-19"
