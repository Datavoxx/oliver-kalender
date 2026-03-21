# =============================================================================
# config.py — ÄNDRA DESSA VÄRDEN för varje ny klient
# =============================================================================

CLIENT_NAME = "Oliver"          # Klientens förnamn
TIMEZONE    = "Europe/Stockholm"  # IANA timezone: "Europe/Stockholm", "Europe/London", etc.
LANGUAGE    = "Swedish"          # Språk som assistenten pratar: "Swedish", "English", etc.

# Modal — unika namn per klient (inga mellanslag, använd bindestreck)
MODAL_APP_NAME  = "calendar-orchestrator"
MODAL_DICT_NAME = "orchestrator-state"

# Modal secrets — namn på secrets i Modal dashboard
MODAL_SECRET_OPENAI  = "openai-api-key"           # Delad — ändras inte per klient
MODAL_SECRET_AUTH    = "api-auth-token"            # Unikt per klient
MODAL_SECRET_GOOGLE  = "google-calendar-credentials"  # Unikt per klient
MODAL_SECRET_OAUTH   = "google-oauth-app"          # Delad — CLIENT_ID + CLIENT_SECRET, ändras inte per klient

# OAuth callback URL — fyll i EFTER första deploy
# Format: "https://[workspace]--[MODAL_APP_NAME]-auth-callback.modal.run"
# Lämna tom tills vidare, uppdatera sedan i Google Cloud Console också.
AUTH_CALLBACK_URL = ""
