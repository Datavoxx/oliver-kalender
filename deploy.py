import sys
import shutil
import subprocess
import modal

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")

# Read bearer token from admin_state (set by admin_bot.py before GitHub push)
try:
    admin_state = modal.Dict.from_name("admin-state", create_if_missing=False)
    token = admin_state.get("clients", {}).get(client, {}).get("auth_token")
    if token:
        subprocess.run(
            ["modal", "secret", "create", f"api-auth-token-{client}", f"API_AUTH_TOKEN={token}", "--force"],
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
