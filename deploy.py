import sys
import shutil
import subprocess
import importlib.util
import modal

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")

# Load config to check interface
spec = importlib.util.spec_from_file_location("config", "config.py")
cfg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfg)
interface = getattr(cfg, "INTERFACE", "slack")

# Read all credentials from admin_state (set by admin_bot.py before GitHub push)
try:
    admin_state = modal.Dict.from_name("admin-state", create_if_missing=False)
    client_info = admin_state.get("clients", {}).get(client, {})

    # Bearer token
    token = client_info.get("auth_token")
    if token:
        subprocess.run(
            ["modal", "secret", "create", f"api-auth-token-{client}", f"API_AUTH_TOKEN={token}", "--force"],
            check=True,
        )

    # Telegram credentials
    if interface == "telegram":
        tg_token = client_info.get("tg_token") or "placeholder"
        tg_chat = client_info.get("tg_chat") or "placeholder"
        subprocess.run(
            ["modal", "secret", "create", f"telegram-client-{client}",
             f"TELEGRAM_BOT_TOKEN={tg_token}", f"TELEGRAM_CHAT_ID={tg_chat}", "--force"],
            check=True,
        )

except Exception as e:
    print(f"Warning: could not read from admin_state: {e}")

# Google credentials placeholder (real credentials stored in admin_state after OAuth)
subprocess.run(
    ["modal", "secret", "create", f"google-calendar-credentials-{client}", "GOOGLE_CALENDAR_CREDENTIALS={}"],
    capture_output=True,
)

subprocess.run(["modal", "deploy", "orchestrator.py"], check=True)
