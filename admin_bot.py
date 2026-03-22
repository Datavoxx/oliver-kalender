import modal
from fastapi.responses import HTMLResponse

app = modal.App("admin-orchestrator")
image = modal.Image.debian_slim().pip_install("requests", "fastapi")

admin_state = modal.Dict.from_name("admin-state", create_if_missing=True)

WORKSPACE = "mmagenzy-info"
OAUTH_CALLBACK_URL = f"https://{WORKSPACE}--admin-orchestrator-oauth-callback.modal.run"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tg(bot_token: str, chat_id: str, text: str) -> None:
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _tg_button(bot_token: str, chat_id: str, text: str, button_label: str, button_url: str) -> None:
    """Send a message with an inline URL button — URL is never touched by Telegram's parser."""
    import requests
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": {
                    "inline_keyboard": [[{"text": button_label, "url": button_url}]]
                },
            },
            timeout=10,
        )
    except Exception:
        pass


def _modal_secret(name: str, env_vars: dict, token_id: str, token_secret: str) -> bool:
    import requests
    try:
        r = requests.put(
            f"https://api.modal.com/v1/secrets/{name}",
            headers={
                "Authorization": f"Token {token_id}:{token_secret}",
                "Content-Type": "application/json",
            },
            json={"workspace_name": WORKSPACE, "env_vars": env_vars},
            timeout=15,
        )
        return r.ok
    except Exception:
        return False


def _github_file(repo: str, path: str, content: str, token: str, message: str) -> bool:
    import requests, base64
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    sha = None
    existing = requests.get(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=headers, timeout=10,
    )
    if existing.ok:
        sha = existing.json().get("sha")
    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
    }
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers=headers, json=body, timeout=15,
    )
    return r.ok


def _set_webhook(bot_token: str, url: str) -> bool:
    import requests
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={"url": url}, timeout=10,
        )
        return r.ok
    except Exception:
        return False


def _build_client_file(name: str) -> str:
    n = name.lower()
    lines = [
        f'CLIENT_NAME = "{name.capitalize()}"',
        f'TIMEZONE    = "Europe/Stockholm"',
        f'LANGUAGE    = "Swedish"',
        f'',
        f'MODAL_APP_NAME  = "calendar-{n}"',
        f'MODAL_DICT_NAME = "{n}-state"',
        f'',
        f'MODAL_SECRET_OPENAI    = "openai-api-key"',
        f'MODAL_SECRET_AUTH      = "api-auth-token-{n}"',
        f'MODAL_SECRET_GOOGLE    = "google-calendar-credentials-{n}"',
    ]
    return "\n".join(lines) + "\n"


def _provision_client(
    name: str,
    github_token: str, github_repo: str,
    modal_id: str, modal_secret_val: str,
    client_id: str,
    bot_token: str, chat_id: str,
) -> None:
    import secrets, urllib.parse

    n = name.lower()
    _tg(bot_token, chat_id, f"⏳ Skapar *{name.capitalize()}*...")

    # 1. Store bearer token in admin_state BEFORE GitHub push
    # deploy.py reads from admin_state to create the Modal secret
    auth_token = secrets.token_hex(32)
    clients_map = admin_state.get("clients", {})
    clients_map[n] = {"auth_token": auth_token}
    admin_state["clients"] = clients_map

    # 2. Push clients/{n}.py to GitHub → triggers GitHub Actions deploy
    ok = _github_file(
        repo=github_repo,
        path=f"clients/{n}.py",
        content=_build_client_file(name),
        token=github_token,
        message=f"Add client {name}",
    )
    if not ok:
        _tg(bot_token, chat_id, "❌ Kunde inte pusha till GitHub. Kontrollera `github-api-token`.")
        return

    _tg(bot_token, chat_id, f"✅ `clients/{n}.py` pushad — GitHub Actions deployas (~2 min)...")

    # 3. Build OAuth URL
    params = {
        "client_id": client_id,
        "redirect_uri": OAUTH_CALLBACK_URL,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        "prompt": "consent",
        "state": n,
    }
    oauth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

    _tg(
        bot_token, chat_id,
        f"*{name.capitalize()} är redo!*\n\n"
        f"🔑 Bearer: `{auth_token}`\n"
        f"📲 Slack — klistra in cURL i n8n",
    )
    _tg_button(
        bot_token, chat_id,
        f"🔗 Skicka den här länken till {name.capitalize()}:",
        button_label=f"Koppla Google Calendar ({name.capitalize()})",
        button_url=oauth_url,
    )


# ── Admin Telegram webhook ────────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("telegram-notifier"),
        modal.Secret.from_name("github-api-token"),
        modal.Secret.from_name("modal-api-token"),
        modal.Secret.from_name("google-oauth-app"),
    ],
    timeout=120,
)
@modal.fastapi_endpoint(method="POST")
def handle_update(update: dict) -> dict:
    import os

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    github_token = os.environ["GITHUB_TOKEN"]
    github_repo = os.environ["GITHUB_REPO"]
    modal_id = os.environ["MODAL_TOKEN_ID"]
    modal_secret_val = os.environ["MODAL_TOKEN_SECRET"]
    client_id = os.environ["GOOGLE_CLIENT_ID"]

    message_obj = update.get("message") or update.get("edited_message")
    if not message_obj:
        return {"ok": True}

    text = (message_obj.get("text") or "").strip()
    incoming_chat = str(message_obj["chat"]["id"])

    # Only respond to the admin
    if incoming_chat != chat_id:
        return {"ok": True}

    state = admin_state.get("state", {"step": "idle"})
    step = state.get("step", "idle")
    text_lower = text.lower()

    # ── "skapa klient {namn}" ────────────────────────────────────────────────
    if any(text_lower.startswith(p) for p in ("skapa klient", "ny klient", "lägg till klient", "create client")):
        words = text.split()
        name = words[-1].capitalize() if len(words) >= 3 else None
        if not name or name.lower() in ("klient", "client"):
            admin_state["state"] = {"step": "awaiting_name"}
            _tg(bot_token, chat_id, "Vad ska klienten heta?")
        else:
            admin_state["state"] = {"step": "idle"}
            _provision_client(name, github_token, github_repo, modal_id, modal_secret_val,
                              client_id, bot_token, chat_id)
        return {"ok": True}

    # ── Awaiting name ─────────────────────────────────────────────────────────
    if step == "awaiting_name" and text:
        name = text.split()[0].capitalize()
        admin_state["state"] = {"step": "idle"}
        _provision_client(name, github_token, github_repo, modal_id, modal_secret_val,
                          client_id, bot_token, chat_id)
        return {"ok": True}

    # ── "avbryt" ─────────────────────────────────────────────────────────────
    if text_lower in ("avbryt", "cancel", "stopp"):
        admin_state["state"] = {"step": "idle"}
        _tg(bot_token, chat_id, "Avbrutet.")
        return {"ok": True}

    # ── Fallback help ─────────────────────────────────────────────────────────
    _tg(bot_token, chat_id, "Kommandon:\n• `skapa klient [namn]`\n• `avbryt`")
    return {"ok": True}


# ── Universal OAuth callback ──────────────────────────────────────────────────

@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("google-oauth-app"),
        modal.Secret.from_name("modal-api-token"),
        modal.Secret.from_name("telegram-notifier"),
        modal.Secret.from_name("github-api-token"),
    ],
    timeout=180,
)
@modal.fastapi_endpoint(method="GET")
def oauth_callback(code: str = None, state: str = "klient", error: str = None):
    import os, json, urllib.parse, urllib.request, requests, time

    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    github_token = os.environ["GITHUB_TOKEN"]
    github_repo = os.environ["GITHUB_REPO"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]
    modal_id = os.environ["MODAL_TOKEN_ID"]
    modal_secret_val = os.environ["MODAL_TOKEN_SECRET"]

    if error:
        _tg(bot_token, chat_id, f"*{state}* — Google-fel: `{error}`")
        return HTMLResponse(f"<h1>Fel: {error}</h1>", status_code=400)
    if not code:
        return HTMLResponse("<h1>Ingen auth-kod mottagen.</h1>", status_code=400)

    # Exchange code for tokens
    token_data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": OAUTH_CALLBACK_URL,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        _tg(bot_token, chat_id,
            f"❌ Google token-fel ({e.code}):\n`{error_body}`\n\n"
            f"redirect\\_uri: `{OAUTH_CALLBACK_URL}`")
        return HTMLResponse(
            f"<h1>Fel vid token-utbyte ({e.code})</h1><p>{error_body}</p>",
            status_code=400,
        )

    credentials = {
        "access_token": tokens.get("access_token", ""),
        "refresh_token": tokens.get("refresh_token", ""),
        "client_id": client_id,
        "client_secret": client_secret,
        "calendar_id": "primary",
    }

    n = state.lower()
    secret_name = f"google-calendar-credentials-{n}"
    ok = _modal_secret(secret_name, {"GOOGLE_CALENDAR_CREDENTIALS": json.dumps(credentials)}, modal_id, modal_secret_val)

    # Store credentials in admin_state (reliable fallback since REST API may fail)
    clients_map = admin_state.get("clients", {})
    if n in clients_map:
        clients_map[n]["google_credentials"] = credentials
        admin_state["clients"] = clients_map

    # Trigger redeploy via GitHub to restart containers with fresh credentials
    _github_file(
        repo=github_repo,
        path=f"clients/{n}.py",
        content=_build_client_file(n),
        token=github_token,
        message=f"Redeploy {n} after OAuth",
    )

    # Get bearer token from admin_state (stored during _provision_client)
    clients_map = admin_state.get("clients", {})
    client_info = clients_map.get(n, {})
    auth_token = client_info.get("auth_token", "OKÄNT")
    interface = client_info.get("interface", "slack")

    # Wait for the Modal app to be live (GitHub Actions may still be deploying)
    import time
    handle_url = f"https://{WORKSPACE}--calendar-{n}-handle-message.modal.run"
    app_ready = False
    for attempt in range(6):
        try:
            r = requests.post(
                handle_url,
                headers={"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"},
                json={"message": "ping", "user_id": "health-check"},
                timeout=10,
            )
            if r.status_code != 404:  # 200 or 403 = app is running
                app_ready = True
                break
        except Exception:
            pass
        if attempt < 5:
            time.sleep(20)

    # Build cURL
    curl_cmd = (
        f'curl -X POST "{handle_url}" \\\n'
        f'  -H "Content-Type: application/json" \\\n'
        f'  -H "Authorization: Bearer {auth_token}" \\\n'
        f'  -d \'{{"message": "hej", "user_id": "{n}"}}\''
    )

    status = "✅ Secret skapad!" if ok else "❌ Secret-fel — kontrollera modal-api-token"
    iface_note = "Telegram-boten är aktiv ✅" if interface == "telegram" else "Klistra in cURL i n8n"

    if not app_ready:
        _tg(bot_token, chat_id,
            f"⚠️ *{state.capitalize()}* — OAuth klart men appen svarar inte än.\n"
            f"GitHub Actions kanske inte kört klart. Vänta 2 min och försök sedan med cURL nedan.")

    _tg(
        bot_token, chat_id,
        f"*{state.capitalize()} är klar!*\n{status}\n"
        f"📲 {iface_note}\n\n"
        f"*cURL:*\n```\n{curl_cmd}\n```",
    )

    return HTMLResponse(
        "<h1>Klart! Du kan stänga den här sidan.</h1>"
        "<p>Kalendern är nu kopplad.</p>"
    )
