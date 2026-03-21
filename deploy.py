import sys
import shutil
import subprocess
import secrets

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")

# Create secrets if they don't exist yet (won't overwrite existing ones)
subprocess.run(
    ["modal", "secret", "create", f"api-auth-token-{client}", f"API_AUTH_TOKEN={secrets.token_hex(32)}"],
    capture_output=True,
)
subprocess.run(
    ["modal", "secret", "create", f"google-calendar-credentials-{client}", "GOOGLE_CALENDAR_CREDENTIALS={}"],
    capture_output=True,
)

subprocess.run(["modal", "deploy", "orchestrator.py"], check=True)
