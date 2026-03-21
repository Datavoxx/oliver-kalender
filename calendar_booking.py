import modal
from fastapi import Header, HTTPException
from datetime import datetime, timezone

app = modal.App("calendar-booking")
image = modal.Image.debian_slim().pip_install("openai", "fastapi")

# Persistent state keyed by user_id — stores partial booking data between turns
booking_state = modal.Dict.from_name("calendar-booking-state", create_if_missing=True)

MISSING_QUESTIONS = {
    "subject": "Vad gäller mötet/bokningen? Berätta lite mer om vad det handlar om.",
    "start_datetime": "När ska det börja? Ange datum och tid.",
    "end_datetime": "När slutar det? Ange sluttid.",
}

SYSTEM_PROMPT = """You are a calendar booking assistant. Extract event details from the user's message.
You must respond ONLY with valid JSON — no prose, no explanation.

Today's date: {today}
Timezone: Europe/Stockholm

Previously collected data: {partial_data}

Extract the following fields from the message:
- subject: what the meeting/event is about (raw description)
- title: a short, professional event title (3-6 words max)
- description: A longer, more detailed description of the event (2-4 sentences). Expand on the subject with relevant context, purpose, or helpful notes. The description should feel like a useful calendar note — not a copy of the title. Write in the same language as the input. Example: if the user says "hämta upp barnen", title = "Hämta upp barnen", description = "Upphämtning av barnen efter skolan eller aktivitet. Kom ihåg att kolla exakt tid och plats i förväg."
- start_datetime: ISO 8601 format (YYYY-MM-DDTHH:MM:SS). Resolve relative dates like "fredag", "imorgon", "nästa måndag" using today's date.
- end_datetime: ISO 8601 format. If the user specifies a duration (e.g. "2 timmar", "1 hour", "45 minuter"), calculate end = start + duration. If NEITHER end time NOR duration is given, set end_datetime to null and add "end_datetime" to missing.
- reminder_minutes: integer. If not specified, use 120.
- missing: array of field names you could not determine. Only include: "subject", "start_datetime", "end_datetime"

Rules:
- If partial_data already has a field, keep it unless the new message overrides it.
- NEVER include "reminder_minutes" in missing — always use 120 as default.
- If start_datetime cannot be determined, set it to null and add "start_datetime" to missing.
- If end_datetime cannot be determined, set it to null and add "end_datetime" to missing.
- If subject cannot be determined, set it to null and add "subject" to missing.
- Respond ONLY with JSON matching this exact schema:

{{
  "subject": "string or null",
  "title": "string or null",
  "description": "string or null",
  "start_datetime": "YYYY-MM-DDTHH:MM:SS or null",
  "end_datetime": "YYYY-MM-DDTHH:MM:SS or null",
  "reminder_minutes": 120,
  "missing": []
}}"""


def _format_confirmation(parsed: dict) -> str:
    start = datetime.fromisoformat(parsed["start_datetime"])
    end = datetime.fromisoformat(parsed["end_datetime"])
    reminder = parsed["reminder_minutes"]

    weekdays_sv = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
    weekday = weekdays_sv[start.weekday()]
    date_str = f"{weekday} {start.day}/{start.month}"
    time_str = f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    if reminder >= 60 and reminder % 60 == 0:
        hours = reminder // 60
        reminder_str = f"{hours} {'timme' if hours == 1 else 'timmar'} innan"
    else:
        reminder_str = f"{reminder} minuter innan"

    return f"{parsed['title']} bokat {date_str} kl {time_str}. Påminnelse {reminder_str}."


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("openai-api-key"),
        modal.Secret.from_name("api-auth-token"),
    ],
    timeout=60,
    min_containers=1,
)
@modal.fastapi_endpoint(method="POST")
def book_event(data: dict, authorization: str = Header(None)) -> dict:
    """
    Parses a natural language booking message and returns structured Google Calendar event data.

    Input:
        message (str): Voice transcription or plain text describing the event
        user_id (str): Slack user ID — used to persist state across turns

    Output (success):
        success: true
        event: Google Calendar-compatible event object
        confirmation: Human-readable confirmation string

    Output (missing info):
        success: false
        missing_field: which field is missing
        question: question to ask the user in Slack
    """
    import os
    import json
    from openai import OpenAI

    # Bearer token auth
    expected_token = os.environ.get("API_AUTH_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    if authorization.replace("Bearer ", "") != expected_token:
        raise HTTPException(status_code=403, detail="Invalid authentication token")

    message = data.get("message", "").strip()
    user_id = data.get("user_id", "anonymous")

    if not message:
        raise HTTPException(status_code=400, detail="'message' field is required")

    # Load any previously saved partial state for this user
    partial_data = booking_state.get(user_id, {})

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    response = client.chat.completions.create(
        model="gpt-5-mini",
        max_completion_tokens=512,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(
                    today=today,
                    partial_data=json.dumps(partial_data, ensure_ascii=False) if partial_data else "none",
                ),
            },
            {"role": "user", "content": message},
        ],
    )

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Failed to parse OpenAI response: {raw}")

    missing = parsed.get("missing", [])

    if missing:
        # Save what we have so far (merge with existing partial state)
        merged = {**partial_data}
        for field in ["subject", "title", "description", "start_datetime", "end_datetime", "reminder_minutes"]:
            if parsed.get(field) is not None:
                merged[field] = parsed[field]
        booking_state[user_id] = merged

        # Ask for the first missing field
        first_missing = missing[0]
        question = MISSING_QUESTIONS.get(first_missing, f"Kan du ange {first_missing}?")

        return {
            "success": False,
            "missing_field": first_missing,
            "question": question,
        }

    # Merge partial_data with current parsed response first.
    # LLM sometimes returns null for fields that already exist in partial_data (forgets the rule).
    # By merging first, we preserve previously collected fields even if LLM omitted them.
    merged = {**partial_data}
    for field in ["subject", "title", "description", "start_datetime", "end_datetime", "reminder_minutes"]:
        if parsed.get(field) is not None:
            merged[field] = parsed[field]

    actually_missing = [f for f in ["subject", "start_datetime", "end_datetime"] if not merged.get(f)]
    if actually_missing:
        booking_state[user_id] = merged

        first_missing = actually_missing[0]
        question = MISSING_QUESTIONS.get(first_missing, f"Kan du ange {first_missing}?")
        return {
            "success": False,
            "missing_field": first_missing,
            "question": question,
        }

    # All required fields present — clear state and return the event
    # (deleted AFTER validation so state survives if something unexpected fails)
    if user_id in booking_state:
        del booking_state[user_id]

    start_dt = parsed["start_datetime"]
    end_dt = parsed["end_datetime"]
    reminder_minutes = parsed.get("reminder_minutes", 120)

    event = {
        "summary": parsed["title"],
        "description": parsed["description"],
        "start": {
            "dateTime": start_dt,
            "timeZone": "Europe/Stockholm",
        },
        "end": {
            "dateTime": end_dt,
            "timeZone": "Europe/Stockholm",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": reminder_minutes},
                {"method": "email", "minutes": 60},
            ],
        },
    }

    return {
        "success": True,
        "event": event,
        "confirmation": _format_confirmation(parsed),
    }
