# Skill: Client Onboarding

## Syfte
Onboarda en ny klient till kalenderassistenten helt via Telegram. Inga terminaler, ingen manuell kopiering, ingen Google Cloud Console-uppdatering krävs.

## Flödet (allt via admin Telegram-bot)

```
1. Du → Telegram admin-bot: "skapa klient [namn]"
2. Bot frågar: Slack eller Telegram?
3. Om Telegram: bot frågar efter bot token + chat ID (format: TOKEN / CHAT_ID)
4. Bot gör automatiskt:
   - Skapar clients/{namn}.py i GitHub → GitHub Actions deployas
   - Skapar api-auth-token-{namn} i Modal
   - Skapar telegram-client-{namn} i Modal (om Telegram)
   - Sätter webhook på klientens Telegram-bot
   - Skickar OAuth-länk till dig + bearer token
5. Du skickar OAuth-länken till klienten
6. Klienten klickar → loggar in med Google → godkänner
7. Automatiskt:
   - google-calendar-credentials-{namn} skapas i Modal
   - Du får Telegram-notis med cURL
8. Klart — klienten kan börja använda boten
```

## Endpoints (admin-orchestrator)

| Endpoint | Metod | Vad |
|---|---|---|
| `handle_update` | POST | Admin Telegram webhook — tar emot dina kommandon |
| `oauth_callback` | GET | Universal OAuth callback för alla klienter |

**OAuth callback URL (en för alla klienter):**
`https://mmagenzy-info--admin-orchestrator-oauth-callback.modal.run`

## Admin-bot kommandon

| Kommando | Beskrivning |
|---|---|
| `skapa klient [namn]` | Starta onboarding för ny klient |
| `avbryt` | Avbryt pågående konversation |

## Modal secrets (globala, sätts en gång)

| Secret | Env-variabler | Syfte |
|---|---|---|
| `google-oauth-app` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Din Google Cloud OAuth-app (publicerad) |
| `modal-api-token` | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_WORKSPACE` | Skapar secrets automatiskt |
| `telegram-notifier` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Admin-bottens credentials |
| `github-api-token` | `GITHUB_TOKEN`, `GITHUB_REPO` | Pushar clients/*.py till GitHub |

## Per klient (skapas automatiskt av admin-boten)

| Secret | Innehåll | Syfte |
|---|---|---|
| `api-auth-token-{namn}` | `API_AUTH_TOKEN` | Bearer token för Slack/n8n |
| `google-calendar-credentials-{namn}` | `GOOGLE_CALENDAR_CREDENTIALS` | OAuth tokens för Google Calendar |
| `telegram-client-{namn}` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Klientens Telegram-bot (om interface=telegram) |

## Vad som skapas per klient i GitHub

`clients/{namn}.py` — genereras automatiskt av admin-boten:
```python
CLIENT_NAME = "Namn"
TIMEZONE    = "Europe/Stockholm"
LANGUAGE    = "Swedish"
INTERFACE   = "telegram"  # eller "slack"

MODAL_APP_NAME  = "calendar-namn"
MODAL_DICT_NAME = "namn-state"

MODAL_SECRET_OPENAI    = "openai-api-key"
MODAL_SECRET_AUTH      = "api-auth-token-namn"
MODAL_SECRET_GOOGLE    = "google-calendar-credentials-namn"
MODAL_SECRET_OAUTH     = "google-oauth-app"
MODAL_SECRET_TELEGRAM  = "telegram-client-namn"  # None för Slack-klienter
```

## GitHub Actions

Push till `clients/*.py` triggar auto-deploy via `.github/workflows/deploy.yml`.
Kräver GitHub secrets: `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`.

## Felsökning

**Admin-boten svarar inte:**
Kontrollera att webhook är satt:
`https://api.telegram.org/bot{TOKEN}/getWebhookInfo`
Sätt om: `python -c "import urllib.request, json; ...setWebhook..."`

**GitHub-push misslyckas:**
Kontrollera `github-api-token` — token behöver Contents: Read/Write på Datavoxx/oliver-kalender.

**OAuth-fel "redirect_uri_mismatch":**
Lägg till `https://mmagenzy-info--admin-orchestrator-oauth-callback.modal.run` i Google Cloud Console → Authorized redirect URIs.

**Token löper ut (7-dagarsfel):**
Google Cloud-appen är i Testing-läge. Gå till OAuth consent screen → Publish App.

**Modal secret skapades inte:**
Kontrollera `modal-api-token` — behöver MODAL_TOKEN_ID, MODAL_TOKEN_SECRET, MODAL_WORKSPACE.
