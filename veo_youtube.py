"""
veo_youtube.py — YouTube upload integration for Veo Studio
══════════════════════════════════════════════════════════

Responsibilities:
  1. OAuth 2.0 flow (desktop app, localhost, one-time browser consent)
  2. Upload a local video file to YouTube with title/description/tags
  3. Token persistence — saves youtube_token.json after first auth
  4. Graceful degradation if credentials file missing

OAuth flow (desktop app):
  - First call to get_authenticated_service() opens a browser tab
  - User logs in + approves → Google redirects to localhost
  - Token saved to youtube_token.json
  - All subsequent calls reuse the token (auto-refreshed when expired)

Called by:
  veo_main.py  → POST /api/youtube/upload
  veo_app.py   → upload queue UI reads job approval state
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("VEO_YOUTUBE")

# ── Constants ─────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

DEFAULT_TAGS = ["ai", "education", "learning", "growth"]

# Paths — both files sit next to veo_main.py
_HERE             = Path(__file__).parent
SECRETS_FILE      = _HERE / "youtube_client_secrets.json"
TOKEN_FILE        = _HERE / "youtube_token.json"

# YouTube API limits
_MAX_TITLE_LEN    = 100
_MAX_DESC_LEN     = 5000
_MAX_TAGS         = 500   # total chars across all tags

# ── Lazy imports ──────────────────────────────────────────────────────────────
try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    _GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    _GOOGLE_LIBS_AVAILABLE = False
    logger.warning(
        "[YouTube] google libs missing — run: "
        "pip install google-auth-oauthlib google-api-python-client"
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    """
    True if youtube_client_secrets.json exists.
    Google libs check is deferred to get_authenticated_service() so tests
    can verify file presence independently of the runtime environment.
    """
    return SECRETS_FILE.exists()


def is_authenticated() -> bool:
    """True if a valid token already exists (no browser needed)."""
    if not is_configured():
        return False
    if not TOKEN_FILE.exists():
        return False
    try:
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        return creds is not None and (creds.valid or creds.refresh_token is not None)
    except Exception:
        return False


def get_authenticated_service():
    """
    Returns an authenticated YouTube API service object.

    Flow:
    1. If token file exists and is valid → use it directly
    2. If token expired but refresh_token present → auto-refresh (silent)
    3. If no token → open browser for first-time consent → save token

    Raises RuntimeError if secrets file is missing or auth fails.
    """
    if not _GOOGLE_LIBS_AVAILABLE:
        raise RuntimeError(
            "Google libraries not installed. Run: "
            "pip install google-auth-oauthlib google-api-python-client"
        )

    if not SECRETS_FILE.exists():
        raise RuntimeError(
            f"youtube_client_secrets.json not found at {SECRETS_FILE}. "
            "Download it from Google Cloud Console → APIs & Services → Credentials."
        )

    creds = None

    # Load existing token
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            logger.warning(f"[YouTube] Could not load token file: {e} — re-authenticating")
            creds = None

    # Refresh if expired
    if creds and not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("[YouTube] Token refreshed successfully")
                _save_token(creds)
            except Exception as e:
                logger.warning(f"[YouTube] Token refresh failed: {e} — re-authenticating")
                creds = None

    # First-time browser consent
    if not creds:
        logger.info("[YouTube] Opening browser for OAuth consent...")
        flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS_FILE), SCOPES)
        # run_local_server opens browser, handles redirect on localhost
        creds = flow.run_local_server(port=0, open_browser=True)
        _save_token(creds)
        logger.info("[YouTube] OAuth consent complete — token saved")

    return build("youtube", "v3", credentials=creds)


def _save_token(creds) -> None:
    try:
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"[YouTube] Token saved to {TOKEN_FILE.name}")
    except Exception as e:
        logger.warning(f"[YouTube] Could not save token: {e}")


# ── Title / description auto-generation ───────────────────────────────────────

def generate_metadata(prompt_text: str) -> dict:
    """
    Auto-generate YouTube title, description, and tags from a prompt.

    Title:       First sentence of prompt, truncated to 100 chars.
    Description: Full prompt text + generation note, truncated to 5000 chars.
    Tags:        DEFAULT_TAGS + any keywords extracted from title words.

    These are defaults — the user edits them in the upload queue UI before upload.
    """
    # Title: strip known prefixes, then take first sentence, truncate to 100 chars
    clean_prompt = prompt_text
    for prefix in ["STATIC. ", "STATIC ", 'Narration "', "Narration "]:
        if clean_prompt.startswith(prefix):
            clean_prompt = clean_prompt[len(prefix):]
    # Also strip inline STATIC prefix anywhere
    clean_prompt = clean_prompt.replace("STATIC. ", "").replace("STATIC ", "")
    first_sentence = clean_prompt.split(".")[0].strip()
    title = first_sentence[:_MAX_TITLE_LEN].strip()
    if not title:
        title = "AI Generated Video"

    # Description: full prompt + attribution footer
    desc_body  = prompt_text[:4900].strip()
    desc_footer = "\n\n---\nGenerated with Veo 3.0 via Veo Studio."
    description = (desc_body + desc_footer)[:_MAX_DESC_LEN]

    # Tags: defaults + significant words from title (4+ chars, not stopwords)
    _STOPWORDS = {"with", "that", "this", "from", "into", "over", "under",
                  "then", "than", "when", "while", "their", "there", "where"}
    title_words = [
        w.lower().strip(".,!?")
        for w in title.split()
        if len(w) >= 4 and w.lower() not in _STOPWORDS
    ]
    tags = list(dict.fromkeys(DEFAULT_TAGS + title_words))  # dedup, preserve order

    return {
        "title":       title,
        "description": description,
        "tags":        tags,
    }


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_video(
    local_path: str,
    title: str,
    description: str,
    tags: list,
    privacy: str = "public",
) -> dict:
    """
    Upload a local video file to YouTube.

    Args:
        local_path:  Absolute path to the local .mp4 file.
        title:       Video title (max 100 chars).
        description: Video description (max 5000 chars).
        tags:        List of tag strings.
        privacy:     'public' | 'unlisted' | 'private'

    Returns dict:
        {
            "status":      "uploaded" | "failed",
            "youtube_id":  "dQw4w9WgXcQ",       # on success
            "youtube_url": "https://youtu.be/...", # on success
            "error":       "...",                  # on failure
        }
    """
    local = Path(local_path)
    if not local.exists():
        return {"status": "failed", "error": f"File not found: {local_path}"}

    # Sanitise inputs
    title       = title[:_MAX_TITLE_LEN].strip() or "AI Generated Video"
    description = description[:_MAX_DESC_LEN].strip()
    tags        = [t.strip() for t in tags if t.strip()]

    try:
        service = get_authenticated_service()

        body = {
            "snippet": {
                "title":       title,
                "description": description,
                "tags":        tags,
                "categoryId":  "27",   # 27 = Education
            },
            "status": {
                "privacyStatus":           privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            str(local),
            mimetype    = "video/mp4",
            resumable   = True,   # resumable upload handles large files safely
            chunksize   = 256 * 1024,  # 256 KB chunks
        )

        logger.info(f"[YouTube] Uploading '{title}' ({local.stat().st_size / (1024*1024):.1f} MB)...")

        request  = service.videos().insert(
            part  = "snippet,status",
            body  = body,
            media_body = media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                logger.info(f"[YouTube] Upload progress: {pct}%")

        video_id  = response["id"]
        video_url = f"https://youtu.be/{video_id}"

        logger.info(f"[YouTube] ✅ Uploaded — {video_url}")

        return {
            "status":      "uploaded",
            "youtube_id":  video_id,
            "youtube_url": video_url,
        }

    except HttpError as e:
        msg = f"YouTube API error {e.resp.status}: {e.content.decode()[:200]}"
        logger.error(f"[YouTube] {msg}")
        return {"status": "failed", "error": msg}

    except RuntimeError as e:
        logger.error(f"[YouTube] Auth error: {e}")
        return {"status": "failed", "error": str(e)}

    except Exception as e:
        logger.error(f"[YouTube] Unexpected error: {e}")
        return {"status": "failed", "error": str(e)}