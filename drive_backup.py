"""Google Drive backup helper — never raises, always returns (bool, str)."""
import os
import logging

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_creds():
    client_id     = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        missing = [k for k, v in {
            "GOOGLE_CLIENT_ID": client_id,
            "GOOGLE_CLIENT_SECRET": client_secret,
            "GOOGLE_REFRESH_TOKEN": refresh_token,
        }.items() if not v]
        return None, f"משתני סביבה חסרים: {', '.join(missing)}"

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    try:
        creds.refresh(Request())
    except Exception as e:
        return None, f"שגיאה ב-OAuth refresh: {e}"

    return creds, None


def backup_to_drive(local_path: str) -> tuple[bool, str]:
    """Upload/update local_path in the configured Drive folder."""
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    if not folder_id:
        return False, "GOOGLE_DRIVE_FOLDER_ID לא מוגדר"

    creds, err = _get_creds()
    if err:
        return False, err

    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        filename = os.path.basename(local_path)

        results = service.files().list(
            q=f"name='{filename}' and '{folder_id}' in parents and trashed=false",
            fields="files(id)",
        ).execute()
        existing = results.get("files", [])

        media = MediaFileUpload(
            local_path,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            resumable=False,
        )

        if existing:
            file_id = existing[0]["id"]
            service.files().update(fileId=file_id, media_body=media).execute()
            logging.info("Drive: updated %s (id=%s)", filename, file_id)
            return True, f"✅ גיבוי עודכן ב-Drive ({filename})"
        else:
            meta = {"name": filename, "parents": [folder_id]}
            f = service.files().create(body=meta, media_body=media, fields="id").execute()
            logging.info("Drive: created %s (id=%s)", filename, f["id"])
            return True, f"✅ גיבוי נוצר ב-Drive ({filename})"

    except Exception as e:
        logging.warning("Drive backup failed: %s", e, exc_info=True)
        return False, f"שגיאת Drive: {e}"
