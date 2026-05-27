"""
Gmail integration service.

Handles:
- OAuth2 authorization flow (get URL → exchange code → store tokens)
- Token refresh (access tokens expire after 1 hour)
- Email search by date range + optional subject keyword
- Full message fetch with headers and body
- Attachment download and save to local storage

OAuth approach: manual HTTP calls (no PKCE) to avoid the stateful Flow
object mismatch that causes "missing code verifier" errors.
"""
import base64
import logging
import os
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import EmailAccount, gen_uuid

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL    = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL   = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL  = "https://oauth2.googleapis.com/revoke"
GMAIL_PROFILE_URL  = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


class GmailService:
    def __init__(self, db: Session):
        self.db = db

    # ── OAuth ──────────────────────────────────────────────────────────────────

    def get_auth_url(self, state: str = "") -> str:
        """Build the Google OAuth2 authorization URL without PKCE."""
        if not settings.GMAIL_CLIENT_ID or not settings.GMAIL_CLIENT_SECRET:
            raise ValueError(
                "GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env. "
                "Create OAuth2 credentials at https://console.cloud.google.com/apis/credentials"
            )
        params = {
            "client_id":     settings.GMAIL_CLIENT_ID,
            "redirect_uri":  settings.GMAIL_REDIRECT_URI,
            "response_type": "code",
            "scope":         " ".join(settings.gmail_scopes_list),
            "access_type":   "offline",   # request refresh token
            "prompt":        "consent",   # always show consent so refresh_token is returned
            "state":         state or "",
        }
        query = urllib.parse.urlencode(params)
        return f"{GOOGLE_AUTH_URL}?{query}"

    def exchange_code(self, code: str, label: str) -> EmailAccount:
        """Exchange authorization code → tokens → store account."""
        # Token exchange via plain POST (no PKCE)
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "redirect_uri":  settings.GMAIL_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise ValueError(f"Token exchange failed: {resp.text}")

        token = resp.json()
        access_token  = token["access_token"]
        refresh_token = token.get("refresh_token")
        expires_in    = token.get("expires_in", 3600)
        expiry        = datetime.utcnow() + timedelta(seconds=expires_in)

        # Get the connected Gmail address using Gmail profile (works with gmail.readonly scope)
        profile_resp = httpx.get(
            GMAIL_PROFILE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if profile_resp.status_code != 200:
            raise ValueError(f"Failed to fetch Gmail profile: {profile_resp.text}")
        email_address = profile_resp.json().get("emailAddress", "")

        # Upsert account
        existing = (
            self.db.query(EmailAccount)
            .filter(EmailAccount.email_address == email_address)
            .first()
        )
        account = existing or EmailAccount(id=gen_uuid(), email_address=email_address)
        account.label         = label or email_address
        account.provider      = "gmail"
        account.access_token  = access_token
        account.refresh_token = refresh_token or account.refresh_token
        account.token_expiry  = expiry
        account.is_active     = True
        account.updated_at    = datetime.utcnow()
        if not existing:
            self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        logger.info(f"Gmail account connected: {email_address}")
        return account

    def disconnect_account(self, account_id: str) -> None:
        """Revoke tokens and mark account inactive."""
        account = self.db.query(EmailAccount).filter(EmailAccount.id == account_id).first()
        if not account:
            return
        if account.access_token:
            try:
                httpx.post(
                    GOOGLE_REVOKE_URL,
                    params={"token": account.access_token},
                    timeout=10,
                )
            except Exception as e:
                logger.warning(f"Token revoke failed (harmless): {e}")
        account.is_active     = False
        account.access_token  = None
        account.refresh_token = None
        self.db.commit()

    # ── Email search ───────────────────────────────────────────────────────────

    def search_messages(
        self,
        account: EmailAccount,
        date_start: str,
        date_end: str,
        extra_query: str = "",
    ) -> List[Dict[str, Any]]:
        """Return [{id, threadId}] for all messages in the date range."""
        service = self._get_service(account)
        # Gmail date format: YYYY/M/D  (no leading zeros needed)
        after  = date_start.replace("-", "/")
        before = date_end.replace("-", "/")
        query  = f"after:{after} before:{before}"
        if extra_query:
            query += f" {extra_query}"

        logger.info(f"Gmail search [{account.email_address}]: {query}")
        messages, page_token = [], None
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, pageToken=page_token, maxResults=500)
                .execute()
            )
            messages.extend(resp.get("messages") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Gmail search returned {len(messages)} messages")
        return messages

    def get_message_detail(self, account: EmailAccount, msg_id: str) -> Dict[str, Any]:
        """Fetch full message: headers, body, attachment metadata."""
        service = self._get_service(account)
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        return self._parse_message(msg)

    def download_attachment(
        self,
        account: EmailAccount,
        msg_id: str,
        attachment_id: str,
        filename: str,
        dest_dir: str,
    ) -> str:
        """Download a single attachment; return saved path."""
        service = self._get_service(account)
        part = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=msg_id, id=attachment_id)
            .execute()
        )
        data = base64.urlsafe_b64decode(part["data"])
        os.makedirs(dest_dir, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "._- " else "_" for c in filename)
        dest = os.path.join(dest_dir, safe_name)
        with open(dest, "wb") as f:
            f.write(data)
        return dest

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_service(self, account: EmailAccount):
        """Build authenticated Gmail API service, refreshing token if needed."""
        # Refresh if expired (or expiring within 60 s)
        if account.token_expiry and account.refresh_token:
            remaining = (account.token_expiry - datetime.utcnow()).total_seconds()
            if remaining < 60:
                self._refresh_access_token(account)

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials(
            token=account.access_token,
            refresh_token=account.refresh_token,
            token_uri=GOOGLE_TOKEN_URL,
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            scopes=settings.gmail_scopes_list,
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def _refresh_access_token(self, account: EmailAccount) -> None:
        """Use refresh token to get a new access token."""
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id":     settings.GMAIL_CLIENT_ID,
                "client_secret": settings.GMAIL_CLIENT_SECRET,
                "refresh_token": account.refresh_token,
                "grant_type":    "refresh_token",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            token = resp.json()
            account.access_token = token["access_token"]
            account.token_expiry = datetime.utcnow() + timedelta(seconds=token.get("expires_in", 3600))
            self.db.commit()
            logger.info(f"Access token refreshed for {account.email_address}")
        else:
            logger.error(f"Token refresh failed for {account.email_address}: {resp.text}")

    @staticmethod
    def _parse_message(msg: Dict) -> Dict[str, Any]:
        """Extract headers, snippet, body text, and attachment metadata."""
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        subject    = headers.get("subject", "(no subject)")
        sender_raw = headers.get("from", "")
        date_str   = headers.get("date", "")
        snippet    = msg.get("snippet", "")

        import re
        m = re.match(r"^(.*?)\s*<([^>]+)>$", sender_raw.strip())
        if m:
            sender_name  = m.group(1).strip().strip('"')
            sender_email = m.group(2).strip().lower()
        else:
            sender_name  = ""
            sender_email = sender_raw.strip().lower()

        received_at = None
        try:
            from email.utils import parsedate_to_datetime
            received_at = parsedate_to_datetime(date_str)
        except Exception:
            pass

        body_text_list: List[str] = []
        attachments: List[Dict]   = []
        GmailService._walk_parts(payload, body_text_list, attachments)

        return {
            "gmail_message_id": msg["id"],
            "subject":          subject,
            "sender_name":      sender_name,
            "sender_email":     sender_email,
            "received_at":      received_at,
            "body_snippet":     snippet[:500],
            "body_text":        " ".join(body_text_list)[:2000],
            "attachments":      attachments,
        }

    @staticmethod
    def _walk_parts(payload: Dict, texts: List[str], attachments: List[Dict]):
        """Recursively walk MIME parts."""
        mime     = payload.get("mimeType", "")
        body     = payload.get("body", {})
        filename = payload.get("filename", "")

        if filename and body.get("attachmentId"):
            attachments.append({
                "name":          filename,
                "size_bytes":    body.get("size", 0),
                "mime":          mime,
                "attachment_id": body["attachmentId"],
            })
        elif mime == "text/plain":
            data = body.get("data", "")
            if data:
                try:
                    texts.append(
                        base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
                    )
                except Exception:
                    pass
        for part in payload.get("parts", []):
            GmailService._walk_parts(part, texts, attachments)

