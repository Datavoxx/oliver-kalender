import modal
from fastapi import Header, HTTPException
from datetime import datetime, timezone

app = modal.App("calendar-orchestrator")
image = (
    modal.Image.debian_slim()
    .pip_install("openai", "fastapi", "google-auth", "google-auth-httplib2", "requests")
    .add_local_python_source("lib")
)

orchestrator_state = modal.Dict.from_name("orchestrator-state", create_if_missing=True)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("openai-api-key"),
        modal.Secret.from_name("api-auth-token"),
        modal.Secret.from_name("google-calendar-credentials"),
    ],
    timeout=60,
    min_containers=1,
)
@modal.fastapi_endpoint(method="POST")
def handle_message(data: dict, authorization: str = Header(None)) -> dict:
    """
    Orchestrator endpoint. Receives Slack messages, manages conversation state,
    classifies intent(s), and executes Google Calendar operations directly.

    Input:  { message: str, user_id: str }
    Output: { reply: str }
    """
    import os
    import json
    from openai import OpenAI
    from lib.prompt import SYSTEM_PROMPT
    from lib.formatters import (
        format_history_for_prompt,
        format_create_confirmation,
        format_update_confirmation,
        format_delete_confirmation,
        format_events_list,
        add_to_history,
        remove_from_history,
        default_state,
    )
    from lib.calendar_client import CalendarClient

    # ── Auth ──────────────────────────────────────────────────────────────────
    expected_token = os.environ.get("API_AUTH_TOKEN")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    if authorization.replace("Bearer ", "") != expected_token:
        raise HTTPException(status_code=403, detail="Invalid token")

    message = data.get("message", "").strip()
    user_id = data.get("user_id", "anonymous")

    if not message:
        raise HTTPException(status_code=400, detail="'message' is required")

    # ── Load state & credentials ───────────────────────────────────────────────
    state = orchestrator_state.get(user_id, default_state())
    event_history = state.get("event_history", [])
    conversation = state.get("conversation", [])

    creds_data = json.loads(os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "{}"))
    cal = CalendarClient(creds_data, event_history)

    # ── Call LLM orchestrator ──────────────────────────────────────────────────
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M (%A)")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    system = SYSTEM_PROMPT.format(
        today=today,
        intent=state.get("intent") or "null",
        fields_json=json.dumps(state.get("fields", {}), ensure_ascii=False) if state.get("fields") else "none",
        awaiting_confirmation=str(state.get("awaiting_confirmation", False)).lower(),
        event_history_json=format_history_for_prompt(event_history),
        last_reply=state.get("last_reply") or "none",
    )

    # Operation item schema (reused in array)
    operation_schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": ["create", "update", "delete", "list", "unclear", "chat"]},
            "fields": {"type": "object"},
            "missing": {"type": "array", "items": {"type": "string"}},
            "reply": {"type": "string"},
            "ready": {"type": "boolean"},
            "awaiting_confirmation": {"type": "boolean"},
            "cancelled": {"type": "boolean"},
        },
        "required": ["intent", "fields", "missing", "reply", "ready", "awaiting_confirmation", "cancelled"],
        "additionalProperties": False,
    }

    response = client.chat.completions.create(
        model="gpt-4.1",
        max_tokens=2048,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "calendar_response",
                "strict": False,
                "schema": {
                    "type": "object",
                    "properties": {
                        "operations": {
                            "type": "array",
                            "items": operation_schema,
                        },
                        "reply": {"type": "string"},
                        "all_ready": {"type": "boolean"},
                    },
                    "required": ["operations", "reply", "all_ready"],
                    "additionalProperties": False,
                },
            },
        },
        messages=[
            {"role": "system", "content": system},
            *conversation[-10:],
            {"role": "user", "content": message},
        ],
    )

    llm = json.loads(response.choices[0].message.content)

    def _save_and_reply(reply_text: str, new_state: dict, reset_conversation: bool = False) -> dict:
        """Save conversation turn to state and return reply."""
        base = [] if reset_conversation else conversation
        new_conv = base + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply_text},
        ]
        new_state["conversation"] = new_conv[-10:]
        orchestrator_state[user_id] = new_state
        return {"reply": reply_text}

    operations = llm.get("operations", [])
    if not operations:
        return _save_and_reply(
            "Vad vill du göra? Jag kan boka, ändra eller ta bort events i din kalender.",
            default_state(event_history),
        )

    # ── Single chat / unclear op ───────────────────────────────────────────────
    if len(operations) == 1:
        op = operations[0]
        intent = op.get("intent", "unclear")

        # Handle cancelled
        if op.get("cancelled"):
            reply_text = op.get("reply") or llm.get("reply") or "Okej, inget ändrat."
            return _save_and_reply(reply_text, default_state(event_history))

        if intent in ("chat", "unclear"):
            reply_text = op.get("reply") or llm.get("reply") or "Vad vill du göra?"
            return _save_and_reply(reply_text, default_state(event_history, last_reply=state.get("last_reply", "")))

    # ── Not all ready — ask for missing info ───────────────────────────────────
    if not llm.get("all_ready"):
        reply_text = llm.get("reply") or "Kan du berätta mer?"
        # Persist the first incomplete single op for continuation
        if len(operations) == 1:
            op = operations[0]
            return _save_and_reply(reply_text, {
                "intent": op.get("intent"),
                "fields": {**state.get("fields", {}), **op.get("fields", {})},
                "missing": op.get("missing", []),
                "awaiting_confirmation": op.get("awaiting_confirmation", False),
                "event_history": event_history,
                "last_reply": state.get("last_reply", ""),
                "pending_operations": [],
            })
        # Multiple ops — persist all for follow-up
        return _save_and_reply(reply_text, {
            "intent": None,
            "fields": {},
            "missing": [],
            "awaiting_confirmation": False,
            "event_history": event_history,
            "last_reply": state.get("last_reply", ""),
            "pending_operations": operations,
        })

    # ── Execute all ready operations ───────────────────────────────────────────
    confirmations = []
    new_history = event_history

    for op in operations:
        intent = op.get("intent")
        fields = {**state.get("fields", {}), **op.get("fields", {})}

        if intent in ("chat", "unclear"):
            reply_text = op.get("reply") or llm.get("reply") or ""
            if reply_text:
                confirmations.append(reply_text)
            continue

        if op.get("cancelled"):
            confirmations.append(op.get("reply") or "Okej, inget ändrat.")
            continue

        if intent == "create":
            # Safety: catch missing or hallucinated 00:00 start time
            start_dt_str = fields.get("start_datetime", "")
            msg_lower = message.lower()
            conv_text = " ".join(m.get("content", "") for m in conversation).lower()
            user_said_midnight = any(t in msg_lower or t in conv_text for t in ["00:00", "00.00", "midnatt"])
            if not start_dt_str or (start_dt_str.endswith("T00:00:00") and not user_said_midnight):
                confirmations.append(f"Kunde inte boka '{fields.get('title', 'event')}' — tid saknas. Berätta vilken tid!")
                continue

            # Safety: end_datetime <= start_datetime → assume crosses midnight
            from datetime import timedelta
            start_dt = datetime.fromisoformat(fields["start_datetime"])
            end_dt = datetime.fromisoformat(fields["end_datetime"])
            if end_dt <= start_dt:
                fields["end_datetime"] = (end_dt + timedelta(days=1)).isoformat()

            event_body: dict = {
                "summary": fields.get("title") or fields.get("summary"),
                "description": fields.get("description", ""),
                "start": {"dateTime": fields["start_datetime"], "timeZone": "Europe/Stockholm"},
                "end": {"dateTime": fields["end_datetime"], "timeZone": "Europe/Stockholm"},
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": fields.get("reminder_minutes", 30)},
                        {"method": "email", "minutes": 60},
                    ],
                },
            }
            if fields.get("location"):
                event_body["location"] = fields["location"]
            if fields.get("attendees"):
                event_body["attendees"] = [{"email": e} for e in fields["attendees"]]
            if fields.get("recurrence"):
                event_body["recurrence"] = [fields["recurrence"]]

            result = cal.request("POST", cal.base_url, json=event_body)
            new_history = add_to_history(new_history, result["id"], result.get("summary", ""), fields["start_datetime"])
            confirmations.append(format_create_confirmation(fields, html_link=result.get("htmlLink")))

        elif intent == "update":
            found = cal.find_event(fields.get("event_identifier", {}))
            if found is None:
                confirmations.append("Hittade inget matchande event att uppdatera. Kan du vara mer specifik?")
                continue
            if "multiple" in found:
                options = "\n".join(f"• {e['summary']} ({e['start'][:10]})" for e in found["multiple"][:5])
                confirmations.append(f"Hittade flera möjliga events:\n{options}\n\nVilket menar du?")
                continue

            changes = fields.get("changes", {})
            patch_body: dict = {}
            if "summary" in changes:
                patch_body["summary"] = changes["summary"]
            if "start_datetime" in changes:
                patch_body["start"] = {"dateTime": changes["start_datetime"], "timeZone": "Europe/Stockholm"}
            if "end_datetime" in changes:
                patch_body["end"] = {"dateTime": changes["end_datetime"], "timeZone": "Europe/Stockholm"}
            if "description" in changes:
                patch_body["description"] = changes["description"]
            if "location" in changes:
                patch_body["location"] = changes["location"]
            if "reminder_minutes" in changes:
                patch_body["reminders"] = {
                    "useDefault": False,
                    "overrides": [{"method": "popup", "minutes": changes["reminder_minutes"]}],
                }
            if "recurrence" in changes:
                patch_body["recurrence"] = [changes["recurrence"]]

            patch_result = cal.request("PATCH", f"{cal.base_url}/{found['event_id']}", json=patch_body)
            new_history = add_to_history(new_history, found["event_id"], changes.get("summary", found["summary"]), changes.get("start_datetime", found["start"]))
            confirmations.append(format_update_confirmation(found, changes, html_link=patch_result.get("htmlLink")))

        elif intent == "delete":
            found = cal.find_event(fields.get("event_identifier", {}))
            if found is None:
                confirmations.append("Hittade inget matchande event att ta bort. Kan du vara mer specifik?")
                continue
            if "multiple" in found:
                options = "\n".join(f"• {e['summary']} ({e['start'][:10]})" for e in found["multiple"][:5])
                confirmations.append(f"Hittade flera möjliga events:\n{options}\n\nVilket ska tas bort?")
                continue

            cal.request("DELETE", f"{cal.base_url}/{found['event_id']}")
            new_history = remove_from_history(new_history, found["event_id"])
            confirmations.append(format_delete_confirmation(found))

        elif intent == "list":
            date_str = fields.get("date")
            if not date_str:
                confirmations.append("Vilket datum vill du kolla?")
                continue
            events = cal.list_events(date_str)
            confirmations.append(format_events_list(events, date_str))

    reply = "\n\n".join(c for c in confirmations if c)
    if not reply:
        reply = "Klart!"

    return _save_and_reply(reply, default_state(new_history, last_reply=reply), reset_conversation=True)
