import sys
import shutil
import subprocess

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")

# Create placeholder Google credentials if secret doesn't exist yet (OAuth not done)
subprocess.run(
    ["modal", "secret", "create", f"google-calendar-credentials-{client}", "GOOGLE_CALENDAR_CREDENTIALS={}"],
    capture_output=True,  # ignore error if secret already exists
)

subprocess.run(["modal", "deploy", "orchestrator.py"], check=True)
