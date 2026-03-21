import modal
import config
from fastapi import Header, HTTPException
from datetime import datetime, timezone

app = modal.App(config.MODAL_APP_NAME)
image = (
    modal.Image.debian_slim()
    .pip_install("openai", "fastapi", "google-auth", "google-auth-httplib2", "requests")
    .add_local_python_source("lib")
    .add_local_python_source("config")
)

orchestrator_state = modal.Dict.from_name(config.MODAL_DICT_NAME, create_if_missing=True)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name(config.MODAL_SECRET_OPENAI),
        modal.Secret.from_name(config.MODAL_SECRET_AUTH),
        modal.Secret.from_name(config.MODAL_SECRET_GOOGLE),
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
                "start": {"dateTime": fields["start_datetime"], "timeZone": config.TIMEZONE},
                "end": {"dateTime": fields["end_datetime"], "timeZone": config.TIMEZONE},
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
                patch_body["start"] = {"dateTime": changes["start_datetime"], "timeZone": config.TIMEZONE}
            if "end_datetime" in changes:
                patch_body["end"] = {"dateTime": changes["end_datetime"], "timeZone": config.TIMEZONE}
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


# ── OAuth helpers ──────────────────────────────────────────────────────────────

def _send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    """Send a message to Telegram. Fails silently."""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _create_modal_secret(secret_name: str, env_vars: dict, token_id: str, token_secret: str, workspace: str) -> tuple:
    """Create or update a Modal secret via REST API. Returns (ok, error_text)."""
    import requests
    try:
        resp = requests.put(
            f"https://api.modal.com/v1/secrets/{secret_name}",
            headers={
                "Authorization": f"Token {token_id}:{token_secret}",
                "Content-Type": "application/json",
            },
            json={"workspace_name": workspace, "env_vars": env_vars},
            timeout=15,
        )
        return resp.ok, "" if resp.ok else resp.text
    except Exception as e:
        return False, str(e)


# ── OAuth endpoints ────────────────────────────────────────────────────────────

_oauth_image = (
    modal.Image.debian_slim()
    .pip_install("fastapi", "requests")
    .add_local_python_source("config")
)


@app.function(
    image=_oauth_image,
    secrets=[
        modal.Secret.from_name(config.MODAL_SECRET_OAUTH),
        modal.Secret.from_name("telegram-notifier"),
    ],
)
@modal.fastapi_endpoint(method="GET")
def auth_start(client: str = "klient"):
    """
    Steg 1: Besök /auth/start?client=oliver
    Skickar Google OAuth-länken till dig via Telegram.
    """
    import os, urllib.parse
    from fastapi.responses import HTMLResponse

    if not config.AUTH_CALLBACK_URL:
        return HTMLResponse(
            "<h1>Sätt AUTH_CALLBACK_URL i config.py och redeploya.</h1>"
            f"<p>Format: <code>https://[workspace]--{config.MODAL_APP_NAME}-auth-callback.modal.run</code></p>",
            status_code=400,
        )

    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "redirect_uri": config.AUTH_CALLBACK_URL,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
        "state": client,
    }
    google_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    _send_telegram(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text=f"*Länk för {client}:*\n{google_url}",
    )

    return HTMLResponse(
        f"<h1>Länk skickad till Telegram!</h1>"
        f"<p>Skicka länken till {client} och be dem klicka på den.</p>"
    )


@app.function(
    image=_oauth_image,
    secrets=[
        modal.Secret.from_name(config.MODAL_SECRET_OAUTH),
        modal.Secret.from_name("modal-api-token"),
        modal.Secret.from_name("telegram-notifier"),
    ],
)
@modal.fastapi_endpoint(method="GET")
def auth_callback(code: str = None, state: str = "klient", error: str = None):
    """
    Steg 2: Google redirectar hit efter att klienten godkänt.
    Skapar Modal secret automatiskt + skickar notis till Telegram.
    """
    import os, json, urllib.parse, urllib.request
    from fastapi.responses import HTMLResponse

    if error:
        _send_telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"],
                       f"*{state}* — Google-fel: {error}")
        return HTMLResponse(f"<h1>Fel: {error}</h1>", status_code=400)
    if not code:
        return HTMLResponse("<h1>Ingen auth-kod mottagen.</h1>", status_code=400)

    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]

    # Byt auth-kod mot tokens
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": config.AUTH_CALLBACK_URL,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read())

    credentials = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "client_id": client_id,
        "client_secret": client_secret,
        "calendar_id": "primary",
    }

    # Skapa Modal secret automatiskt
    secret_name = f"google-calendar-credentials-{state}"
    ok, _ = _create_modal_secret(
        secret_name=secret_name,
        env_vars={"GOOGLE_CALENDAR_CREDENTIALS": json.dumps(credentials)},
        token_id=os.environ["MODAL_TOKEN_ID"],
        token_secret=os.environ["MODAL_TOKEN_SECRET"],
        workspace=os.environ["MODAL_WORKSPACE"],
    )

    # Bygg cURL-kommando
    handle_url = f"https://{os.environ['MODAL_WORKSPACE']}--{config.MODAL_APP_NAME}-handle-message.modal.run"
    curl_cmd = (
        f'curl -X POST "{handle_url}" \\\n'
        f'  -H "Content-Type: application/json" \\\n'
        f'  -H "Authorization: Bearer DITT_TOKEN" \\\n'
        f'  -d \'{{"message": "hej", "user_id": "{state}"}}\''
    )

    if ok:
        status_line = f"*Secret `{secret_name}` skapad automatiskt!*"
    else:
        modal_cmd = f'modal secret create {secret_name} GOOGLE_CALENDAR_CREDENTIALS=\'{json.dumps(credentials)}\''
        status_line = f"*Secret misslyckades* — kor manuellt:\n```\n{modal_cmd}\n```"

    _send_telegram(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text=f"*{state} ar klar!*\n{status_line}\n\n*cURL:*\n```\n{curl_cmd}\n```",
    )

    return HTMLResponse(
        "<h1>Klart! Du kan stanga den har sidan.</h1>"
        "<p>Kalendern ar nu kopplad.</p>"
    )
