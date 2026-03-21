# Skill: Client Onboarding

## Syfte
Onboarda en ny klient till kalenderassistenten helt via Telegram. Inga terminaler, ingen manuell kopiering.

## Flödet (allt via admin Telegram-bot)

```
1. Du → Telegram admin-bot: "skapa klient [namn]"
2. Bot gör automatiskt:
   - Sparar bearer token i admin_state
   - Skapar clients/{namn}.py i GitHub → GitHub Actions deployas (~2 min)
   - Skickar bearer token + OAuth-länk till dig
3. Du skickar OAuth-länken till klienten
4. Klienten klickar → loggar in med Google → godkänner
5. Automatiskt:
   - Google credentials sparas i admin_state
   - GitHub Actions re-deployas (container startas om med nya credentials)
   - Du får Telegram-notis med cURL
6. Klistra in cURL i n8n → klart
```

## Interface
Alla klienter använder **Slack/n8n** (HTTP endpoint). Ingen Telegram-interface för klienter.

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
| `modal-api-token` | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | Används för diagnostik |
| `telegram-notifier` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Admin-bottens credentials |
| `github-api-token` | `GITHUB_TOKEN`, `GITHUB_REPO` | Pushar clients/*.py till GitHub |

## Per klient (skapas automatiskt)

| Secret | Innehåll | Skapas av |
|---|---|---|
| `api-auth-token-{namn}` | `API_AUTH_TOKEN` | deploy.py (via admin_state) |
| `google-calendar-credentials-{namn}` | `GOOGLE_CALENDAR_CREDENTIALS` | placeholder vid deploy, real data i admin_state efter OAuth |

## Google credentials — hur det fungerar
- Vid deploy: `google-calendar-credentials-{namn}` skapas som placeholder `{}`
- orchestrator.py läser först från Modal secret, om tom → läser från `admin_state["clients"][namn]["google_credentials"]`
- oauth_callback sparar real credentials i admin_state direkt (ingen REST API)

## Vad som skapas per klient i GitHub

`clients/{namn}.py` — genereras automatiskt:
```python
CLIENT_NAME = "Namn"
TIMEZONE    = "Europe/Stockholm"
LANGUAGE    = "Swedish"

MODAL_APP_NAME  = "calendar-namn"
MODAL_DICT_NAME = "namn-state"

MODAL_SECRET_OPENAI    = "openai-api-key"
MODAL_SECRET_AUTH      = "api-auth-token-namn"
MODAL_SECRET_GOOGLE    = "google-calendar-credentials-namn"
```

## GitHub Actions

Push till `clients/*.py` triggar auto-deploy via `.github/workflows/deploy.yml`.
Kräver GitHub secrets: `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`.

## n8n setup per klient

```
Slack Trigger
  → HTTP Request (POST calendar-{namn}-handle-message.modal.run)
    Header: Authorization: Bearer {token}
    Body: { "message": "{{$json.text}}", "user_id": "{{$json.user}}" }
  → Slack: Send {{ $json.reply }}
```

## Felsökning

**GitHub Actions misslyckas — secret not found:**
Kontrollera att admin_state har rätt data: `modal python -c "import modal; print(modal.Dict.from_name('admin-state').get('clients'))"`

**500 Internal Server Error — refresh_token:**
Klienten har inte gjort OAuth än. Skicka OAuth-länken igen.

**Endpoint stopped:**
Redeploya inte manuellt. Skapa klienten på nytt via `skapa klient [namn]` i Telegram.

**Modal endpoint-limit (max 8):**
Free tier = 8 endpoints. admin-orchestrator tar 2, varje klient tar 1. Max ~5 aktiva klienter + admin.
