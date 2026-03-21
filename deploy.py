import sys
import shutil
import subprocess

client = sys.argv[1]
shutil.copy(f"clients/{client}.py", "config.py")
subprocess.run(["modal", "deploy", "orchestrator.py"], check=True)
