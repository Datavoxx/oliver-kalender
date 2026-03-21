import sys
import shutil
import subprocess

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")

# Create Google credentials placeholder if not yet created (OAuth not done)
subprocess.run(
    ["modal", "secret", "create", f"google-calendar-credentials-{client}", "GOOGLE_CALENDAR_CREDENTIALS={}"],
    capture_output=True,
)

subprocess.run(["modal", "deploy", "orchestrator.py"], check=True)
