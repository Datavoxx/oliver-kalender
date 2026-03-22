# Kalender-projektet — Komplett Referens

Detta är den primära referensfilen för projektet. CLAUDE.md hanterar generell Modal/n8n-setup. Den här filen är källan till sanning för hur **detta specifika projekt** fungerar.

---

## Syfte

En AI-kalenderassistent per klient. Klienten skriver ett meddelande i Slack → AI:n förstår vad de vill → utför åtgärden i Google Kalender → svarar på svenska.

---

## Arkitektur

```
[Klient skriver i Slack]
        ↓
[Slack Trigger — n8n]
        ↓
[HTTP Request — n8n]  →  POST calendar-{namn}-handle-message.modal.run
        ↓                    Authorization: Bearer {token}
[orchestrator.py — Modal]    Body: { message, user_id }
        ↓
[GPT-4.1 — intent + fältextraktion]
   intents: create | update | delete | list | unclear | chat
   stödjer multi-operation (max 5 per meddelande)
        ↓
[Google Calendar API — direkt via OAuth2]
        ↓
{ reply: str }  →  n8n  →  Slack: Send {{ $json.reply }}
```

**Exakt 3 noder i n8n:** Slack Trigger → HTTP Request → Slack Send. Aldrig mer.

---

## Filer och deras roll

```
orchestrator.py          ← Modal endpoint per klient. Hanterar HTTP, auth, LLM-anrop, Calendar API-utförande.
lib/
  prompt.py              ← SYSTEM_PROMPT som skickas till GPT-4.1. Definierar ALL logik: intents, fält, regler.
  formatters.py          ← Svenska bekräftelsemeddelanden + state-hjälpfunktioner.
  calendar_client.py     ← Google Calendar API (OAuth2 token-refresh + event lookup).
config.py                ← Genereras automatiskt från clients/{namn}.py vid deploy. Läses av orchestrator.py.
clients/
  {namn}.py              ← En fil per klient. Definierar konstanter som config.py.
admin_bot.py             ← Admin Telegram-bot. Skapar klienter, hanterar OAuth-callback.
deploy.py                ← Körs av GitHub Actions. Kopierar clients/{namn}.py → config.py, skapar secrets, deployas.
.github/workflows/
  deploy.yml             ← Triggas av push till clients/*.py. Kör deploy.py för rätt klient.
```

---

## Per-klient-struktur

Varje klient har:
- **En Modal-app**: `calendar-{namn}` med endpoint `handle-message`
- **En klientfil**: `clients/{namn}.py`
- **Två Modal-secrets**: `api-auth-token-{namn}` + `google-calendar-credentials-{namn}`
- **En Modal Dict**: `{namn}-state` (konversationsminne)

### clients/{namn}.py (genereras av admin_bot.py)
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

---

## Modal Secrets — global översikt

| Secret | Env-variabler | Används av |
|---|---|---|
| `openai-api-key` | `OPENAI_API_KEY` | orchestrator.py (alla klienter) |
| `api-auth-token-{namn}` | `API_AUTH_TOKEN` | orchestrator.py (per klient) |
| `google-calendar-credentials-{namn}` | `GOOGLE_CALENDAR_CREDENTIALS` | orchestrator.py (per klient) |
| `google-oauth-app` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | admin_bot.py |
| `telegram-notifier` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | admin_bot.py |
| `github-api-token` | `GITHUB_TOKEN`, `GITHUB_REPO` | admin_bot.py |
| `modal-api-token` | `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` | admin_bot.py |

### google-calendar-credentials JSON-struktur
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "client_id": "415390219435-4kitatik6ole5ma1b3uhm7kcaeri6kdi.apps.googleusercontent.com",
  "client_secret": "...",
  "calendar_id": "primary"
}
```
Sparas i admin_state["clients"][namn]["google_credentials"] + Modal Secret.

---

## Admin Telegram-bot (admin_bot.py)

Du styr allt via Telegram. Klienterna använder Slack.

### Kommandon
| Kommando | Vad händer |
|---|---|
| `skapa klient [namn]` | Startar hela onboarding-flödet |
| `avbryt` | Avbryter pågående konversation |

### Endpoints (admin-orchestrator)
| Endpoint | Metod | Syfte |
|---|---|---|
| `handle_update` | POST | Tar emot dina Telegram-meddelanden |
| `oauth_callback` | GET | Universal OAuth-callback för alla klienter |

**OAuth callback URL (en för alla):**
`https://mmagenzy-info--admin-orchestrator-oauth-callback.modal.run`

---

## Client Onboarding — komplett flöde

```
1. Du → Telegram: "skapa klient [namn]"
         ↓
2. admin_bot.py:
   - Genererar bearer token
   - Sparar token i admin_state["clients"][namn]["auth_token"]
   - Pushar clients/{namn}.py till GitHub
         ↓
3. GitHub Actions (deploy.yml):
   - Kopierar clients/{namn}.py → config.py
   - Läser bearer token från admin_state → skapar Modal secret api-auth-token-{namn}
   - Skapar placeholder-secret google-calendar-credentials-{namn} (tomt)
   - Kör: modal deploy orchestrator.py
   - Endpoint live: calendar-{namn}-handle-message.modal.run
         ↓
4. admin_bot.py skickar till dig via Telegram:
   - Bearer token
   - OAuth-länk (Google login för klienten)
         ↓
5. Du skickar OAuth-länken till klienten
         ↓
6. Klienten klickar → loggar in med Google → godkänner kalenderåtkomst
         ↓
7. oauth_callback tar emot Google-tokens automatiskt:
   - Sparar credentials i admin_state["clients"][namn]["google_credentials"]
   - Försöker skapa Modal Secret via REST API (kan misslyckas)
   - Triggar re-deploy via GitHub push
   - Väntar upp till 2 min på att appen ska svara (6 försök × 20s)
   - Skickar cURL till dig i Telegram
         ↓
8. Du klistrar in cURL i n8n → klart
```

### Google Credentials — hur det faktiskt fungerar
orchestrator.py läser credentials i två steg:
1. Läs från Modal Secret `google-calendar-credentials-{namn}`
2. Om tom/saknas refresh_token → läs från `admin_state["clients"][namn]["google_credentials"]`

Step 2 är backup-lösning eftersom Modal REST API:t ibland misslyckas.

---

## State-struktur per klient (Modal Dict: `{namn}-state`)

```json
{
  "intent": "create|update|delete|null",
  "fields": {},
  "missing": [],
  "awaiting_confirmation": false,
  "event_history": [
    { "event_id": "abc123", "summary": "Tandläkare", "start": "2026-03-15T10:00:00" }
  ],
  "last_reply": "Tandläkare inbokat fredag 15/3 kl 10:00–11:00.",
  "conversation": [
    {"role": "user", "content": "boka tandläkare fredag 10-11"},
    {"role": "assistant", "content": "Tandläkare inbokat fredag 15/3 kl 10:00–11:00."}
  ],
  "pending_operations": []
}
```

- `event_history` — max 20 entries, används för update/delete lookup
- `conversation` — senaste 10 meddelanden, skickas till GPT-4.1
- `last_reply` — senaste bekräftelse, används om klienten frågar "har du bokat den?"

---

## LLM — GPT-4.1 Output Schema

```json
{
  "operations": [
    {
      "intent": "create|update|delete|list|unclear|chat",
      "fields": {},
      "missing": ["field_name"],
      "reply": "Fråga på svenska om info saknas. Tom sträng om ready=true.",
      "ready": true,
      "awaiting_confirmation": false,
      "cancelled": false
    }
  ],
  "reply": "Toppnivå-svar. Tomt om all_ready=true.",
  "all_ready": true
}
```

Max 5 operationer per meddelande. all_ready=true → orchestrator utför alla operationer.

---

## Deploy

```bash
# Deploya en specifik klient (körs normalt av GitHub Actions)
PYTHONUTF8=1 python deploy.py {namn}

# Deploya admin_bot manuellt
PYTHONUTF8=1 modal deploy admin_bot.py
```

---

## Begränsningar

| Begränsning | Detalj |
|---|---|
| Modal Free Tier: max 8 endpoints | admin-orchestrator tar 2 → max 6 aktiva klienter |
| Konversationsminne | Senaste 10 meddelanden (5 par) |
| Event history | Senaste 20 skapade events |

---

## Skill-underhåll — VIKTIG REGEL

**När du ändrar kod, uppdatera alltid rätt skill-fil.**

| Om du ändrar... | Uppdatera skill... |
|---|---|
| orchestrator.py (flöde, schema, state) | `orchestrator-agent.md` |
| lib/prompt.py (regler, fält, frågor) | relevant operation-skill (create/update/delete/list) |
| lib/formatters.py (bekräftelseformat) | relevant operation-skill |
| lib/calendar_client.py (API-anrop) | relevant operation-skill |
| admin_bot.py (onboarding-flöde) | `client-onboarding.md` |
| deploy.py | `client-onboarding.md` |

Skills beskriver INTENT och REGLER. Koden är vad som faktiskt körs. De måste stämma överens.
