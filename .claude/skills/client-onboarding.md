# Skill: Client Onboarding

## Syfte
Onboarda en ny klient till kalenderassistenten på ett seamless sätt via Telegram. Inga terminaler eller manuell kopiering krävs av klienten.

## Flödet

```
1. Du → öppnar /auth/start?client=[namn] i webbläsaren
2. Telegram → du får Google OAuth-länken
3. Du skickar länken till klienten (Telegram, SMS, email)
4. Klienten klickar → loggar in med Google → godkänner
5. Automatiskt:
   - Modal secret "google-calendar-credentials-[namn]" skapas
   - Du får Telegram-notis: "[namn] klar! + cURL"
6. Klienten ser: "Klart! Stäng sidan."
```

## Endpoints

| Endpoint | Metod | Vad |
|---|---|---|
| `/auth/start?client=[namn]` | GET | Skickar OAuth-länk till Telegram |
| `/auth/callback` | GET | Tar emot Google auth-kod, skapar secret, notifierar |

## Modal secrets (globala, sätts en gång)

| Secret | Env-variabler | Syfte |
|---|---|---|
| `google-oauth-app` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Din Google Cloud OAuth-app |
| `modal-api-token` | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, `MODAL_WORKSPACE` | Skapar secrets automatiskt |
| `telegram-notifier` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Notiser till dig |

## Per klient (skapas automatiskt via flödet)

Secret: `google-calendar-credentials-[klientnamn]`
Env-variabel: `GOOGLE_CALENDAR_CREDENTIALS` (JSON)

## Checklista för ny klient

```
1. Nytt GitHub-repo från template (oliver-kalender)
2. Redigera config.py:
   - CLIENT_NAME = "KlientNamn"
   - MODAL_APP_NAME = "calendar-klientnamn"
   - MODAL_DICT_NAME = "klientnamn-state"
   - MODAL_SECRET_AUTH = "api-auth-token-klientnamn"
   - MODAL_SECRET_GOOGLE = "google-calendar-credentials-klientnamn"
3. Skapa bearer token secret:
   modal secret create api-auth-token-klientnamn API_AUTH_TOKEN=xxx
4. modal deploy orchestrator.py
5. Kopiera auth-callback URL → sätt i config.AUTH_CALLBACK_URL → redeploy
6. Lägg till callback URL i Google Cloud Console (authorized redirect URIs)
7. Öppna /auth/start?client=klientnamn i webbläsaren
8. Skicka länken (från Telegram) till klienten
9. Klienten godkänner → du får Telegram-notis med cURL
10. Klart!
```

## Felsökning

**Modal secret skapades inte automatiskt:**
Telegram-notisen innehåller ett manuellt `modal secret create`-kommando som fallback.

**"Sätt AUTH_CALLBACK_URL i config.py":**
Callback-URL saknas. Kör `modal deploy`, kopiera URL:en som slutar med `-auth-callback.modal.run`, sätt in i config.py, redeploya.

**Token löper ut efter 7 dagar:**
Google Cloud-appen är i "Testing"-läge. Publicera till Production i Google Cloud Console → OAuth consent screen → Publish App.
