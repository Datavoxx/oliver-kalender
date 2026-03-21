from datetime import datetime


def format_history_for_prompt(event_history: list) -> str:
    if not event_history:
        return "none"
    lines = []
    for ev in event_history[-10:]:
        start = ev.get("start", "")[:16].replace("T", " ")
        lines.append(f'  - "{ev.get("summary", "")}" on {start} (id: {ev.get("event_id", "")})')
    return "\n" + "\n".join(lines)


def rrule_to_swedish(rrule: str) -> str:
    """Convert RRULE string to human-readable Swedish, e.g. 'varje måndag'."""
    rule = rrule.replace("RRULE:", "")
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    freq = parts.get("FREQ", "")
    byday = parts.get("BYDAY", "")
    count = parts.get("COUNT", "")
    until = parts.get("UNTIL", "")

    day_map = {
        "MO": "måndag", "TU": "tisdag", "WE": "onsdag", "TH": "torsdag",
        "FR": "fredag", "SA": "lördag", "SU": "söndag",
    }

    if freq == "DAILY":
        base = "varje dag"
    elif freq == "WEEKLY":
        days = [day_map.get(d.strip(), d) for d in byday.split(",") if d.strip()]
        if not days:
            base = "varje vecka"
        elif set(days) == {"måndag", "tisdag", "onsdag", "torsdag", "fredag"}:
            base = "varje vardag"
        elif len(days) == 1:
            base = f"varje {days[0]}"
        else:
            base = "varje " + " och ".join(days)
    elif freq == "MONTHLY":
        base = "varje månad"
    elif freq == "YEARLY":
        base = "varje år"
    else:
        base = "återkommande"

    if count:
        base += f" ({count} gånger)"
    elif until and len(until) >= 8:
        y, m, d = until[:4], until[4:6], until[6:8]
        base += f" till {int(d)}/{int(m)}/{y}"

    return base


def format_create_confirmation(fields: dict, html_link: str = None) -> str:
    start = datetime.fromisoformat(fields["start_datetime"])
    end = datetime.fromisoformat(fields["end_datetime"])
    weekdays_sv = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
    weekday = weekdays_sv[start.weekday()]
    date_str = f"{weekday} {start.day}/{start.month}"
    time_str = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
    title = fields.get("title") or fields.get("summary", "Event")
    reminder = fields.get("reminder_minutes", 120)
    if reminder >= 60 and reminder % 60 == 0:
        hours = reminder // 60
        reminder_str = f"{hours} {'timme' if hours == 1 else 'timmar'} innan"
    else:
        reminder_str = f"{reminder} minuter innan"
    if fields.get("recurrence"):
        recurrence_sv = rrule_to_swedish(fields["recurrence"])
        msg = f"{title} inbokat {recurrence_sv} kl {time_str} (första gången {date_str}). Påminnelse {reminder_str}."
    else:
        msg = f"{title} inbokat {date_str} kl {time_str}. Påminnelse {reminder_str}."
    if html_link:
        msg += f"\n{html_link}"
    return msg


def format_update_confirmation(found: dict, changes: dict, html_link: str = None) -> str:
    parts = [f"{found['summary']} är uppdaterat."]
    if "start_datetime" in changes:
        start = datetime.fromisoformat(changes["start_datetime"])
        weekdays_sv = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
        parts.append(
            f"Ny tid: {weekdays_sv[start.weekday()]} {start.day}/{start.month} kl {start.strftime('%H:%M')}."
        )
    msg = " ".join(parts)
    if html_link:
        msg += f"\n{html_link}"
    return msg


def format_delete_confirmation(found: dict) -> str:
    return f"{found['summary']} har tagits bort från kalendern."


def add_to_history(history: list, event_id: str, summary: str, start: str) -> list:
    history = [e for e in history if e.get("event_id") != event_id]
    history.append({"event_id": event_id, "summary": summary, "start": start})
    return history[-20:]


def remove_from_history(history: list, event_id: str) -> list:
    return [e for e in history if e.get("event_id") != event_id]


def format_events_list(events: list, date_str: str) -> str:
    try:
        date = datetime.fromisoformat(date_str)
        weekdays_sv = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
        day_label = f"{weekdays_sv[date.weekday()]} {date.day}/{date.month}"
    except (ValueError, TypeError):
        day_label = date_str

    if not events:
        return f"Du har inga bokningar {day_label}."

    lines = [f"Du har {len(events)} {'bokning' if len(events) == 1 else 'bokningar'} {day_label}:"]
    for ev in events:
        summary = ev.get("summary", "Namnlöst event")
        start_raw = ev.get("start", {})
        end_raw = ev.get("end", {})
        start_dt = start_raw.get("dateTime") or start_raw.get("date", "")
        end_dt = end_raw.get("dateTime") or end_raw.get("date", "")
        try:
            start_time = datetime.fromisoformat(start_dt).strftime("%H:%M")
            end_time = datetime.fromisoformat(end_dt).strftime("%H:%M")
            time_str = f"{start_time}–{end_time}"
        except (ValueError, TypeError):
            time_str = start_dt[:10] if start_dt else "heldag"
        lines.append(f"• {time_str} — {summary}")
    return "\n".join(lines)


def default_state(event_history: list = None, last_reply: str = "", conversation: list = None) -> dict:
    return {
        "intent": None,
        "fields": {},
        "missing": [],
        "awaiting_confirmation": False,
        "event_history": event_history or [],
        "last_reply": last_reply,
        "conversation": conversation or [],
        "pending_operations": [],
    }
