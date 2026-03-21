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
  → LLM: intent=list, fields={date: "2026-03-07"}, ready=true
  → orchestrator: cal.list_events("2026-03-07")
  → Calendar API: GET /calendars/primary/events?timeMin=...&timeMax=...
  → format_events_list(events, date_str)
  → reply: "Du har 3 bokningar lördag 7/3:\n• 10:00–12:00 — Möte med Oliver\n..."
```

## CalendarClient.list_events (lib/calendar_client.py)

```python
def list_events(self, date_str: str) -> list:
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": f"{date_str}T00:00:00+01:00",
        "timeMax": f"{date_str}T23:59:59+01:00",
        "maxResults": 20,
    }
    result = self.request("GET", self.base_url, params=params)
    return result.get("items", [])
```

## format_events_list (lib/formatters.py)

```python
def format_events_list(events: list, date_str: str) -> str:
    # Returns Swedish summary of all events on the given date
    # Empty → "Du har inga bokningar {dag} {datum}."
    # With events → "Du har N bokningar {dag} {datum}:\n• HH:MM–HH:MM — Titel\n..."
```

## Orchestrator branch (orchestrator.py)

```python
elif intent == "list":
    date_str = merged_fields.get("date")
    if not date_str:
        # ask for date
        ...
    events = cal.list_events(date_str)
    reply = format_events_list(events, date_str)
    return _save_and_reply(reply, default_state(event_history, last_reply=reply))
```

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
- All-day events (no dateTime) show as "heldag"
- maxResults=20 prevents oversized responses
