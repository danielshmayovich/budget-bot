"""
One-time script: run locally to get a Google Drive refresh token.

Usage:
    pip install google-auth-oauthlib
    python get_drive_token.py

It will open a browser, ask you to log in and grant Drive access, then
save credentials (including refresh_token) to token.json.

NEVER commit token.json or client_secret*.json to git.
"""
import json
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# Accept client_secret filename as argument, or look for default name
if len(sys.argv) > 1:
    secret_file = sys.argv[1]
else:
    candidates = sorted(Path(".").glob("client_secret*.json"))
    if not candidates:
        sys.exit("ERROR: no client_secret*.json found. Pass the filename as argument:\n"
                 "  python get_drive_token.py client_secret_XYZ.json")
    secret_file = str(candidates[0])
    print(f"Using: {secret_file}")

flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
creds = flow.run_local_server(port=0, open_browser=False)

out = {
    "client_id":     creds.client_id,
    "client_secret": creds.client_secret,
    "refresh_token": creds.refresh_token,
    "token_uri":     creds.token_uri,
}

Path("token.json").write_text(json.dumps(out, indent=2))
print("\n✅ token.json saved.")
print("\nCopy these values to Railway environment variables:")
print(f"  GOOGLE_CLIENT_ID     = {creds.client_id}")
print(f"  GOOGLE_CLIENT_SECRET = {creds.client_secret}")
print(f"  GOOGLE_REFRESH_TOKEN = {creds.refresh_token}")
