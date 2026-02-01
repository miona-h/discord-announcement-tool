#!/usr/bin/env python3
"""
GoogleカレンダーAPI連携モジュール

予定を自動取得し、告知文生成用のevent_data形式に変換します。
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False


SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_flow(redirect_uri: str, client_id: str = None, client_secret: str = None):
    if not GOOGLE_API_AVAILABLE:
        return None
    client_id = client_id or _get_client_id()
    client_secret = client_secret or _get_client_secret()
    if not client_id or not client_secret:
        return None
    return Flow.from_client_config(
        {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )


def _get_client_id() -> Optional[str]:
    try:
        import streamlit as st
        return st.secrets.get("GOOGLE_CLIENT_ID")
    except Exception:
        pass
    return None


def _get_client_secret() -> Optional[str]:
    try:
        import streamlit as st
        return st.secrets.get("GOOGLE_CLIENT_SECRET")
    except Exception:
        pass
    return None


def get_authorization_url(redirect_uri: str) -> Optional[str]:
    if not GOOGLE_API_AVAILABLE:
        return None
    flow = _get_flow(redirect_uri)
    if flow is None:
        return None
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return auth_url


def exchange_code_for_credentials(redirect_uri: str, code: str) -> Optional[Credentials]:
    if not GOOGLE_API_AVAILABLE:
        return None
    flow = _get_flow(redirect_uri)
    if flow is None:
        return None
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_to_dict(creds: "Credentials") -> Dict:
    return {
        "token": creds.token,
        "refresh_token": getattr(creds, "refresh_token", None),
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def dict_to_credentials(d: Dict) -> Optional["Credentials"]:
    if not GOOGLE_API_AVAILABLE or not d:
        return None
    return Credentials(
        token=d.get("token"),
        refresh_token=d.get("refresh_token"),
        token_uri=d.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=d.get("client_id"),
        client_secret=d.get("client_secret"),
        scopes=d.get("scopes", SCOPES),
    )


def refresh_credentials_if_needed(creds: "Credentials") -> tuple:
    """
    トークンが期限切れの場合は更新する。
    戻り値: (creds, 更新された辞書 or None)。
    辞書が返った場合は session_state を更新すること。
    """
    if not GOOGLE_API_AVAILABLE or creds is None:
        return (creds, None)
    try:
        from google.auth.transport.requests import Request
        if creds.expired and getattr(creds, "refresh_token", None):
            creds.refresh(Request())
            return (creds, credentials_to_dict(creds))
    except Exception:
        pass
    return (creds, None)


def get_calendar_service(credentials: "Credentials"):
    if not GOOGLE_API_AVAILABLE:
        return None
    return build("calendar", "v3", credentials=credentials)


def fetch_upcoming_events(
    credentials: "Credentials",
    max_results: int = 20,
    days_ahead: int = 14,
) -> List[Dict]:
    if not GOOGLE_API_AVAILABLE:
        return []
    try:
        service = get_calendar_service(credentials)
        if service is None:
            return []
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        from datetime import timedelta
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return events_result.get("items", [])
    except HttpError as e:
        raise e
    except Exception:
        return []


def _extract_instagram_from_description(description: str) -> str:
    if not description:
        return ""
    match = re.search(r"https://www\.instagram\.com/[^\s\)]+", description)
    if match:
        return match.group(0).rstrip(")")
    match = re.search(r"Instagram[リンク：:\s]*([^\s\)]+)", description, re.I)
    if match:
        url = match.group(1).strip()
        if "instagram.com" in url:
            return url
    return ""


def _format_date_time(start: Dict) -> tuple:
    if "dateTime" in start:
        dt_str = start["dateTime"]
        try:
            if "T" in dt_str:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                return (f"{dt.month}/{dt.day}", f"{dt.hour:02d}:{dt.minute:02d}")
        except Exception:
            pass
    if "date" in start:
        try:
            dt = datetime.strptime(start["date"], "%Y-%m-%d")
            return (f"{dt.month}/{dt.day}", "00:00")
        except Exception:
            pass
    return ("", "")


def api_event_to_event_data(api_event: Dict, parse_event_name_fn) -> Dict[str, Any]:
    summary = api_event.get("summary", "")
    description = api_event.get("description", "") or ""
    start = api_event.get("start", {})

    event_data = {}
    if summary and parse_event_name_fn:
        parsed = parse_event_name_fn(summary)
        event_data.update(parsed)

    date_str, time_str = _format_date_time(start)
    event_data["date"] = date_str
    event_data["time"] = time_str

    instagram_url = _extract_instagram_from_description(description)
    if instagram_url:
        event_data["instagram_url"] = instagram_url
    else:
        event_data["instagram_url"] = event_data.get("instagram_url", "")

    event_data["_raw_summary"] = summary
    event_data["_raw_description"] = description[:200] if description else ""

    return event_data
