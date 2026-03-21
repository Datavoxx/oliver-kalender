"""
Run this script locally to get Google OAuth2 tokens for the orchestrator.
It starts a local server on port 8080 to capture the auth code automatically.

Usage:
    python get_tokens.py
"""

import json
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import webbrowser

CLIENT_ID = "641808401793-jdd6b9bl1lcq0lb3hf93ikij52tq5p9c.apps.googleusercontent.com"
CLIENT_SECRET = input("Paste your Client Secret: ").strip()

SCOPE = "https://www.googleapis.com/auth/calendar"
REDIRECT_URI = "http://localhost:8080"

params = {
    "client_id": CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "response_type": "code",
    "scope": SCOPE,
    "access_type": "offline",
    "prompt": "consent",
}
auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)

code = None

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Klart! Du kan stanga webblesaren och ga tillbaka till terminalen.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
    def log_message(self, *_):
        pass

server = HTTPServer(("localhost", 8080), Handler)
thread = threading.Thread(target=server.handle_request)
thread.start()

print("\nOppnar webblasaren for Google-inloggning...")
webbrowser.open(auth_url)
print("Logga in och ge tillstand. Vanter pa auth-kod...\n")
thread.join(timeout=120)

# Exchange code for tokens
token_data = urllib.parse.urlencode({
    "code": code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": REDIRECT_URI,
    "grant_type": "authorization_code",
}).encode()

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token",
    data=token_data,
    method="POST",
)
req.add_header("Content-Type", "application/x-www-form-urlencoded")

with urllib.request.urlopen(req) as resp:
    tokens = json.loads(resp.read())

credentials = {
    "access_token": tokens["access_token"],
    "refresh_token": tokens.get("refresh_token", ""),
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "calendar_id": "primary",
}

output = json.dumps(credentials, indent=2)
print("\n✅ Success! Here are your credentials:\n")
print(output)

with open("calendar_credentials.json", "w") as f:
    json.dump(credentials, f, indent=2)

print("\nSaved to calendar_credentials.json")
print("\nNext step — create the Modal secret:")
print('modal secret create google-calendar-credentials GOOGLE_CALENDAR_CREDENTIALS=\'%s\'' % json.dumps(credentials))
