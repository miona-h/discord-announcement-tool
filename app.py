#!/usr/bin/env python3
"""
Discordオンラインイベント配信文章 自動生成ツール - Web版

使い方:
    streamlit run app.py
"""

import streamlit as st
import sys
import os
import csv
import io
import re
import urllib.request
import urllib.parse
from datetime import date, datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_calendar import parse_event_name
from generate_announcement import AnnouncementGenerator
from monthly_overview import build_monthly_overview
from config import CALENDAR_EXCLUDE_TITLES
from google.oauth2.credentials import Credentials

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_CSV_PATH = os.path.join(APP_DIR, "templates", "templates.csv")
TEMPLATE_CSV_FIELDS = ["event_type", "template", "channels", "match_keywords"]
TEMPLATE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d2BkB9xIQZnFVdiV7Bk-x3S2yA7XAmAgUPa79iLJrTo/edit?usp=sharing"
TEMPLATE_SHEET_ID = "1d2BkB9xIQZnFVdiV7Bk-x3S2yA7XAmAgUPa79iLJrTo"
TEMPLATE_SHEET_GID = "0"
TEMPLATE_SHEET_RANGE = "テンプレート!A:D"

try:
    from streamlit_oauth import OAuth2Component
    STREAMLIT_OAUTH_AVAILABLE = True
except Exception:
    STREAMLIT_OAUTH_AVAILABLE = False

# Googleカレンダー連携（オプション）
try:
    from google_calendar_client import (
        GOOGLE_API_AVAILABLE,
        get_authorization_url,
        exchange_code_for_credentials,
        credentials_to_dict,
        dict_to_credentials,
        refresh_credentials_if_needed,
        fetch_calendar_list,
        fetch_upcoming_events,
        api_event_to_event_data,
        fetch_spreadsheet_values,
    )
except ImportError:
    GOOGLE_API_AVAILABLE = False


st.set_page_config(
    page_title="Discord告知文生成ツール",
    page_icon="📢",
    layout="centered",
)

st.title("📢 Discord告知文 自動生成ツール")
st.caption("SnsClubオンラインイベント用の告知文章を生成します")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE_LIST = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]
GOOGLE_SCOPE_STR = " ".join(GOOGLE_SCOPE_LIST)


def _use_streamlit_oauth() -> bool:
    if not STREAMLIT_OAUTH_AVAILABLE:
        return False
    if not hasattr(st, "secrets"):
        return False
    return bool(st.secrets.get("GOOGLE_CLIENT_ID") and st.secrets.get("GOOGLE_CLIENT_SECRET"))


def _get_default_channel_name(event_type: str) -> str:
    """イベント種別からチャンネル名を返す"""
    if not event_type:
        return "交流会のお知らせ"
    if "万垢生限定オン会" in event_type or "万垢" in event_type:
        return "万垢お知らせチャンネル"
    if "ジャンル特化グルコン" in event_type:
        return "ジャンル特化グルコンのお知らせ"
    if "講師対談" in event_type or "生徒対談" in event_type or "オン会" in event_type:
        return "交流会のお知らせ"
    return "交流会のお知らせ"


def _split_channels(channels_text: str) -> list[str]:
    """カンマ・改行区切りの配信先をリスト化する"""
    if not channels_text:
        return []
    normalized = str(channels_text).replace("、", ",").replace("\n", ",")
    return [ch.strip() for ch in normalized.split(",") if ch.strip()]


def _join_channels(channels: list[str]) -> str:
    return ", ".join([ch for ch in channels if ch])


def _get_default_channel_names(event_type: str) -> list[str]:
    """CSVに配信先がない場合のデフォルト配信先"""
    if "万垢生限定オン会" in str(event_type) or "万垢" in str(event_type):
        return ["万垢お知らせチャンネル", "講師お知らせ", "専属講師チーム"]
    return [_get_default_channel_name(event_type)]


def _load_template_records() -> list[dict]:
    """テンプレートCSVから event_type/template/channels/match_keywords を読み込む"""
    records = []
    if not os.path.exists(TEMPLATE_CSV_PATH):
        return records
    try:
        with open(TEMPLATE_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                event_type = (row.get("event_type") or "").strip()
                template = (row.get("template") or "").strip()
                if not event_type or not template:
                    continue
                channels = (row.get("channels") or "").strip()
                if not channels:
                    channels = _join_channels(_get_default_channel_names(event_type))
                records.append({
                    "event_type": event_type,
                    "template": template,
                    "channels": channels,
                    "match_keywords": (row.get("match_keywords") or "").strip(),
                })
    except Exception as e:
        st.error(f"テンプレートCSVの読み込みに失敗しました: {e}")
    return records


def _parse_template_csv(text: str) -> list[dict]:
    """Googleスプレッドシートから取得したCSVを検証する"""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fieldnames = [str(name or "").strip() for name in (reader.fieldnames or [])]
    required = {"event_type", "template", "channels", "match_keywords"}
    missing = required - set(fieldnames)
    if missing:
        raise ValueError(
            "1行目に event_type, template, channels, match_keywords の4列が必要です。"
            f" 不足: {', '.join(sorted(missing))}"
        )

    records = []
    for row_number, row in enumerate(reader, start=2):
        event_type = (row.get("event_type") or "").strip()
        template = (row.get("template") or "").strip()
        channels = (row.get("channels") or "").strip()
        match_keywords = (row.get("match_keywords") or "").strip()
        if not event_type and not template and not channels and not match_keywords:
            continue
        if not event_type or not template:
            raise ValueError(f"{row_number}行目: event_type と template は必須です。")
        records.append({
            "event_type": event_type,
            "template": template,
            "channels": channels or _join_channels(_get_default_channel_names(event_type)),
            "match_keywords": match_keywords,
        })
    if not records:
        raise ValueError("有効なテンプレートが1件もありません。")
    return records


def _sheet_values_to_records(values: list[list], fields: list[str]) -> list[dict]:
    """スプレッドシートの行配列を辞書一覧に変換する"""
    if not values:
        return []
    headers = [str(v).strip() for v in values[0]]
    missing = set(fields) - set(headers)
    if missing:
        raise ValueError(f"必要な列がありません: {', '.join(sorted(missing))}")
    records = []
    for row_number, row in enumerate(values[1:], start=2):
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        rec = {headers[i]: str(padded[i]).strip() for i in range(len(headers))}
        if any(rec.get(field, "") for field in fields):
            records.append(rec)
    return records


def _parse_template_sheet_values(values: list[list]) -> list[dict]:
    records = _sheet_values_to_records(values, TEMPLATE_CSV_FIELDS)
    normalized = []
    for row_number, rec in enumerate(records, start=2):
        event_type = rec.get("event_type", "").strip()
        template = rec.get("template", "").strip()
        channels = rec.get("channels", "").strip()
        if not event_type or not template:
            raise ValueError(f"テンプレート {row_number}行目: event_type と template は必須です。")
        normalized.append({
            "event_type": event_type,
            "template": template,
            "channels": channels or _join_channels(_get_default_channel_names(event_type)),
            "match_keywords": rec.get("match_keywords", "").strip(),
        })
    if not normalized:
        raise ValueError("有効なテンプレートが1件もありません。")
    return normalized


def _fetch_template_records_from_sheet() -> list[dict]:
    """GoogleスプレッドシートをCSVとして手動取得する"""
    query = urllib.parse.urlencode({
        "format": "csv",
        "gid": TEMPLATE_SHEET_GID,
        "_": int(datetime.now().timestamp()),
    })
    export_url = f"https://docs.google.com/spreadsheets/d/{TEMPLATE_SHEET_ID}/export?{query}"
    request = urllib.request.Request(export_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        text = response.read().decode("utf-8-sig")
    return _parse_template_csv(text)


def _save_template_records(records: list[dict]) -> tuple[bool, str]:
    """テンプレート一覧をCSVへ保存する"""
    try:
        os.makedirs(os.path.dirname(TEMPLATE_CSV_PATH), exist_ok=True)
        tmp_path = TEMPLATE_CSV_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=TEMPLATE_CSV_FIELDS)
            writer.writeheader()
            for rec in records:
                event_type = (rec.get("event_type") or "").strip()
                template = (rec.get("template") or "").strip()
                channels = (rec.get("channels") or "").strip()
                if event_type and template:
                    writer.writerow({
                        "event_type": event_type,
                        "template": template,
                        "channels": channels or _join_channels(_get_default_channel_names(event_type)),
                        "match_keywords": (rec.get("match_keywords") or "").strip(),
                    })
        os.replace(tmp_path, TEMPLATE_CSV_PATH)
        return True, "保存しました"
    except Exception as e:
        return False, str(e)


def _sync_templates_from_google_sheet(creds) -> int:
    """Googleスプレッドシートの最新版を取得してローカルキャッシュへ反映する。"""
    template_values = fetch_spreadsheet_values(creds, TEMPLATE_SHEET_ID, TEMPLATE_SHEET_RANGE)
    sheet_records = _parse_template_sheet_values(template_values)
    ok, msg = _save_template_records(sheet_records)
    if not ok:
        raise RuntimeError(msg)
    return len(sheet_records)


def _keyword_groups(text: str) -> list[list[str]]:
    """判定キーワードを解析する。カンマ区切りはAND、|区切りはOR。"""
    groups = []
    for raw_group in str(text or "").split("|"):
        keywords = [k.strip() for k in re.split(r"[,、+\n]+", raw_group) if k.strip()]
        if keywords:
            groups.append(keywords)
    return groups


def _apply_template_keyword_match(event_data: dict) -> dict:
    """イベント名と判定キーワードを照合し、最も具体的なテンプレート種別を適用する。"""
    result = event_data.copy()
    event_name = (
        str(result.get("_raw_summary", "") or "").strip()
        or str(result.get("event_name", "") or "").strip()
    )
    if not event_name:
        return result

    best = None
    for row_index, rec in enumerate(_load_template_records()):
        for keywords in _keyword_groups(rec.get("match_keywords", "")):
            if all(keyword in event_name for keyword in keywords):
                # キーワード数が多く、文字数が長い（より具体的な）ルールを優先する。
                score = (len(keywords), sum(len(keyword) for keyword in keywords), -row_index)
                if best is None or score > best[0]:
                    best = (score, rec.get("event_type", ""))
    if best and best[1]:
        result["event_type"] = best[1]
    return result


def _find_template_records(event_type: str) -> list[dict]:
    """同じイベント種別のテンプレート行をすべて返す"""
    target = str(event_type or "").strip()
    return [rec for rec in _load_template_records() if rec.get("event_type") == target]


def _get_channel_names(event_type: str) -> list[str]:
    """イベント種別に応じた配信先一覧を返す"""
    records = _find_template_records(event_type)
    channels = []
    for rec in records:
        for ch in _split_channels(rec.get("channels", "")):
            if ch not in channels:
                channels.append(ch)
    return channels or _get_default_channel_names(event_type)


def _generate_announcement_items(generator: AnnouncementGenerator, event_data: dict) -> list[dict]:
    """テンプレート行ごとに告知文と配信先を生成する"""
    event_type = (event_data.get("event_type") or "").strip()
    records = _find_template_records(event_type)
    items = []
    if records:
        for rec in records:
            msg = generator.generate_from_template(rec.get("template", ""), event_data)
            if not msg:
                continue
            channels = _split_channels(rec.get("channels", "")) or _get_default_channel_names(event_type)
            for channel in channels:
                items.append({"message": msg, "channel": channel})
    else:
        msg = generator.generate(event_data)
        if msg:
            for channel in _get_default_channel_names(event_type):
                items.append({"message": msg, "channel": channel})
    return items


def _get_post_date_time(event_type: str, event_date: str, event_time: str):
    """
    当日告知＝開催当日08:00、事前告知＝前日18:00、まもなく開始＝当日開始15分前 を返す。
    戻り値: (日付文字列 "M/D", 時間文字列 "HH:MM")
    """
    from datetime import datetime, timedelta
    year = datetime.now().year
    post_date_str, post_time_str = str(event_date), str(event_time)
    try:
        parts = str(event_date).strip().split("/")
        if len(parts) >= 2:
            m, d = int(parts[0]), int(parts[1])
        else:
            return (event_date, "18:00" if "事前告知" in str(event_type) else event_time)
        if "当日告知" in str(event_type):
            post_date_str = f"{m}/{d}"
            post_time_str = "08:00"
        elif "事前告知" in str(event_type):
            event_dt = datetime(year, m, d)
            prev = event_dt - timedelta(days=1)
            post_date_str = f"{prev.month}/{prev.day}"
            post_time_str = "18:00"
        elif "間もなく開始" in str(event_type) or "まもなく" in str(event_type):
            post_date_str = f"{m}/{d}"
            t = str(event_time).strip()
            if ":" in t:
                parts_t = t.split(":")
                h = int(parts_t[0])
                mi = int(parts_t[1]) if len(parts_t) > 1 else 0
                t_dt = datetime(year, m, d, h, mi) - timedelta(minutes=15)
                post_date_str = f"{t_dt.month}/{t_dt.day}"
                post_time_str = f"{t_dt.hour:02d}:{t_dt.minute:02d}"
            else:
                post_time_str = t
        else:
            post_date_str = f"{m}/{d}"
            post_time_str = "18:00" if "事前告知" in str(event_type) else str(event_time)
    except Exception:
        post_date_str = event_date
        post_time_str = "08:00" if "当日告知" in str(event_type) else ("18:00" if "事前告知" in str(event_type) else event_time)
    return (post_date_str, post_time_str)


def _handle_oauth_callback():
    q = st.query_params
    code = q.get("code")
    state = q.get("state")
    if code and isinstance(code, list):
        code = code[0]
    if state and isinstance(state, list):
        state = state[0]
    if not code:
        return
    # 既に連携済みでURLにcodeだけ残っている場合：交換せずそのまま表示（rerunしない＝セッション維持）
    if "google_credentials" in st.session_state:
        return
    redirect_uri = os.environ.get("REDIRECT_URI") or (
        st.secrets.get("REDIRECT_URI") if hasattr(st, "secrets") else None
    ) or "http://localhost:8501"
    pkce_map = st.session_state.get("oauth_pkce_map", {})
    code_verifier = pkce_map.get(state) if state else st.session_state.get("oauth_code_verifier")
    try:
        creds = exchange_code_for_credentials(
            redirect_uri,
            code,
            state=state,
            code_verifier=code_verifier,
        )
    except Exception as e:
        st.session_state["oauth_error"] = str(e)
        return
    if creds:
        st.session_state["google_credentials"] = credentials_to_dict(creds)
        st.session_state["oauth_just_completed"] = True
        if "oauth_code_verifier" in st.session_state:
            del st.session_state["oauth_code_verifier"]
        if state and isinstance(pkce_map, dict) and state in pkce_map:
            del pkce_map[state]
            st.session_state["oauth_pkce_map"] = pkce_map
        if "oauth_error" in st.session_state:
            del st.session_state["oauth_error"]
        # rerunしない＝このまま描画を続けて「連携済み」を表示（Streamlit Cloudでrerunするとセッションが消えて空白になるため）
    else:
        st.session_state["oauth_error"] = "トークンの取得に失敗しました。もう一度「Googleカレンダーと連携する」からやり直してください。"

if GOOGLE_API_AVAILABLE and not _use_streamlit_oauth():
    _handle_oauth_callback()

# ページを開き直した際は、そのセッションでGoogle連携が確認でき次第、
# スプレッドシートの最新版を1回だけ自動取得する。
if GOOGLE_API_AVAILABLE and st.session_state.get("google_credentials"):
    if not st.session_state.get("template_sheet_auto_loaded"):
        try:
            auto_creds = dict_to_credentials(st.session_state["google_credentials"])
            auto_creds, updated = refresh_credentials_if_needed(auto_creds)
            if updated is not None:
                st.session_state["google_credentials"] = updated
            auto_count = _sync_templates_from_google_sheet(auto_creds)
            updated_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")
            st.session_state["template_sheet_synced_at"] = updated_at
            st.session_state["template_sheet_sync_message"] = (
                f"リロード時にスプレッドシート最新版を{auto_count}件反映しました。"
            )
            st.session_state["template_sheet_auto_loaded"] = True
            st.session_state.pop("template_sheet_auto_error", None)
        except Exception as e:
            # カレンダー等の利用は止めず、テンプレート管理タブで再試行できるようにする。
            st.session_state["template_sheet_auto_error"] = str(e)

tab_names = ["🔗 Googleカレンダーと連携", "✏️ 手動入力", "📝 テンプレート管理"]
if not GOOGLE_API_AVAILABLE:
    tab_names = ["✏️ 手動入力", "📝 テンプレート管理"]

tabs = st.tabs(tab_names)
tab_idx = 0

if GOOGLE_API_AVAILABLE:
    with tabs[tab_idx]:
        redirect_uri = os.environ.get("REDIRECT_URI") or (
            st.secrets.get("REDIRECT_URI") if hasattr(st, "secrets") else None
        ) or "http://localhost:8501"
        auth_payload = get_authorization_url(redirect_uri)
        auth_url = auth_payload[0] if auth_payload else None
        client_id = st.secrets.get("GOOGLE_CLIENT_ID") if hasattr(st, "secrets") else None
        client_secret = st.secrets.get("GOOGLE_CLIENT_SECRET") if hasattr(st, "secrets") else None

        if "oauth_error" in st.session_state:
            st.error(st.session_state["oauth_error"])
            if st.button("エラーを消す"):
                del st.session_state["oauth_error"]
                st.rerun()
        if "google_credentials" not in st.session_state:
            st.markdown("**Googleカレンダーと連携して、予定を自動で取り込みます**")
            oauth_linked = False
            if _use_streamlit_oauth() and client_id and client_secret:
                try:
                    oauth2 = OAuth2Component(
                        client_id=client_id,
                        client_secret=client_secret,
                        authorize_endpoint=GOOGLE_AUTH_URL,
                        token_endpoint=GOOGLE_TOKEN_URL,
                    )
                    oauth_result = oauth2.authorize_button(
                        name="🔗 Googleカレンダーと連携する",
                        redirect_uri=redirect_uri,
                        scope=GOOGLE_SCOPE_STR,
                        pkce="S256",
                        key="oauth_google_connect",
                    )
                    if oauth_result and isinstance(oauth_result, dict):
                        token_data = oauth_result.get("token", oauth_result)
                        access_token = token_data.get("access_token") or token_data.get("token")
                        if access_token:
                            creds = Credentials(
                                token=access_token,
                                refresh_token=token_data.get("refresh_token"),
                                token_uri=GOOGLE_TOKEN_URL,
                                client_id=client_id,
                                client_secret=client_secret,
                                scopes=GOOGLE_SCOPE_LIST,
                            )
                            st.session_state["google_credentials"] = credentials_to_dict(creds)
                            st.session_state["oauth_just_completed"] = True
                            if "oauth_error" in st.session_state:
                                del st.session_state["oauth_error"]
                            oauth_linked = True
                            st.rerun()
                except Exception as e:
                    err_text = str(e)
                    if "DOES NOT MATCH OR OUT OF DATE" in err_text:
                        # 古いstate付きURLで戻った場合はクエリを捨てて再試行可能にする
                        try:
                            st.query_params.clear()
                        except Exception:
                            pass
                        st.session_state["oauth_error"] = (
                            "認証セッションが期限切れになりました。"
                            " もう一度「Googleカレンダーと連携する」を押してください。"
                        )
                    else:
                        st.session_state["oauth_error"] = f"streamlit-oauth連携エラー: {err_text}"

            # フォールバック（従来フロー）は streamlit-oauth 未使用時のみ表示
            if (not _use_streamlit_oauth()) and (not oauth_linked):
                if auth_url:
                    st.markdown(
                        f'<a href="{auth_url}" style="display:inline-block;padding:0.5rem 1rem;'
                        'background:#FF4B4B;color:white;text-decoration:none;border-radius:0.5rem;font-weight:500;">'
                        '🔗 Googleカレンダーと連携する</a>',
                        unsafe_allow_html=True,
                    )
                    st.caption("クリックしてGoogleでログインし、許可するとこのページに戻り「連携済み」と表示されます。")
                else:
                    st.info("Google連携を使うには、管理者がGoogle CloudでOAuth設定を行う必要があります。")
        else:
            creds_dict = st.session_state["google_credentials"]
            creds = dict_to_credentials(creds_dict)
            if creds is None:
                del st.session_state["google_credentials"]
                st.rerun()

            if st.session_state.get("oauth_just_completed"):
                st.success("✅ 連携が完了しました！「予定を取得」でカレンダーから予定を取り込めます。")
                st.session_state["oauth_just_completed"] = False
            else:
                st.success("Googleカレンダーと連携済みです")
            if st.button("🔓 連携を解除"):
                del st.session_state["google_credentials"]
                st.session_state.pop("template_sheet_auto_loaded", None)
                st.session_state.pop("template_sheet_auto_error", None)
                if "calendar_events" in st.session_state:
                    del st.session_state["calendar_events"]
                if "calendar_list" in st.session_state:
                    del st.session_state["calendar_list"]
                st.rerun()

            # カレンダー一覧を取得（初回のみ）
            if "calendar_list" not in st.session_state:
                with st.spinner("カレンダー一覧を取得しています..."):
                    try:
                        creds, updated = refresh_credentials_if_needed(creds)
                        if updated is not None:
                            st.session_state["google_credentials"] = updated
                        cal_list = fetch_calendar_list(creds)
                        st.session_state["calendar_list"] = cal_list if cal_list else [{"id": "primary", "summary": "メイン"}]
                    except Exception as e:
                        st.warning(f"カレンダー一覧の取得でエラーが発生したため、メインカレンダーのみ表示します: {e}")
                        st.session_state["calendar_list"] = [{"id": "primary", "summary": "メイン"}]

            cal_list = st.session_state.get("calendar_list", [{"id": "primary", "summary": "メイン"}])
            cal_options = [f"{c.get('summary', '')} ({c.get('id', '')})" for c in cal_list]
            cal_ids = [c.get("id", "primary") for c in cal_list]
            cal_idx = st.selectbox("取得するカレンダーを選択", range(len(cal_list)), format_func=lambda i: cal_options[i])
            selected_calendar_id = cal_ids[cal_idx] if cal_ids else "primary"

            fetch_start = st.date_input(
                "取得開始日（この日から1ヶ月分を取得）",
                value=date.today(),
                key="calendar_fetch_start",
            )
            st.caption("例: 3月1日から取りたい場合は 3/1 を選択してください。")

            if st.button("📅 予定を取得（1ヶ月分）"):
                with st.spinner(f"{fetch_start} から1ヶ月分の予定を取得しています..."):
                    try:
                        creds, updated = refresh_credentials_if_needed(creds)
                        if updated is not None:
                            st.session_state["google_credentials"] = updated
                        events = fetch_upcoming_events(
                            creds,
                            calendar_id=selected_calendar_id,
                            max_results=250,
                            days_ahead=31,
                            start_date=fetch_start,
                        )
                        event_data_list = []
                        for ev in events:
                            summary = (ev.get("summary") or "").strip()
                            if not summary:
                                continue
                            if any(exc in summary for exc in CALENDAR_EXCLUDE_TITLES):
                                continue
                            ed = api_event_to_event_data(ev, parse_event_name)
                            ed["_id"] = ev.get("id", "")
                            ed = _apply_template_keyword_match(ed)
                            event_data_list.append(ed)
                        st.session_state["calendar_events"] = event_data_list
                    except Exception as e:
                        st.error(f"予定の取得に失敗しました: {e}")

            if "calendar_events" in st.session_state and st.session_state["calendar_events"]:
                events_list = st.session_state["calendar_events"]
                options = [
                    f"{ed.get('date', '')} {ed.get('time', '')}｜{ed.get('_raw_summary', '')[:40]}"
                    for ed in events_list
                ]
                selected = st.selectbox("告知文を生成する予定を選んでください", range(len(options)), format_func=lambda i: options[i])
                if st.button("📝 この予定で告知文を生成", type="primary"):
                    ed = _apply_template_keyword_match(events_list[selected])
                    for k in ("_id", "_raw_summary", "_raw_description"):
                        ed.pop(k, None)
                    try:
                        generator = AnnouncementGenerator()
                        is_valid, errors = generator.validate_event_data(ed)
                        if not is_valid:
                            st.warning("入力情報に不備があります（手動入力タブで補完してください）")
                            for err in errors:
                                st.write(f"• {err}")
                        else:
                            items = _generate_announcement_items(generator, ed)
                            if items:
                                st.success("告知文を生成しました！")
                                for item_idx, item in enumerate(items):
                                    st.text_area(
                                        f"生成された告知文｜配信先：{item['channel']}",
                                        item["message"],
                                        height=400,
                                        key=f"announcement_output_linked_{item_idx}",
                                    )
                                st.caption("💡 上のテキストを選択して Ctrl+C（Mac: Cmd+C）でコピーできます")
                            else:
                                st.error("告知文の生成に失敗しました")
                    except Exception as e:
                        st.error(f"エラー: {e}")

                st.divider()
                st.markdown("**1ヶ月分を一括生成してスプレッドシート用に出力**")
                if st.button("📋 1ヶ月分の告知文を一括生成", type="primary", key="btn_bulk"):
                    generator = AnnouncementGenerator()
                    rows = []
                    unmatched_events = []
                    for original_ed in events_list:
                        ed = _apply_template_keyword_match(original_ed)
                        event_type_original = str(ed.get("event_type", "") or "").strip()
                        if event_type_original not in generator.templates:
                            event_name = (
                                str(ed.get("_raw_summary", "") or "").strip()
                                or str(ed.get("event_name", "") or "").strip()
                                or "イベント名未設定"
                            )
                            unmatched_events.append({
                                "開催日": ed.get("date", ""),
                                "開始時間": ed.get("time", ""),
                                "イベント名": event_name,
                            })
                        ev_copy = ed.copy()
                        for k in ("_id", "_raw_summary", "_raw_description"):
                            ev_copy.pop(k, None)
                        event_type = ev_copy.get("event_type", "")
                        # 1件の予定につき「事前告知」と「まもなく開始」の2行を出力（全日程に適用）
                        for is_soon in (False, True):
                            if is_soon:
                                if "（事前告知）" not in event_type:
                                    continue
                                ev_row = ev_copy.copy()
                                ev_row["event_type"] = event_type.replace("（事前告知）", "（間もなく開始）")
                            else:
                                ev_row = ev_copy
                            row_type = ev_row.get("event_type", "")
                            post_date, post_time = _get_post_date_time(
                                row_type, ev_row.get("date", ""), ev_row.get("time", "")
                            )
                            is_valid = generator.validate_event_data(ev_row)[0]
                            if not is_valid:
                                continue
                            items = _generate_announcement_items(generator, ev_row)
                            for item in items:
                                rows.append({
                                    "メッセージ": item["message"].replace("\r", "\n"),
                                    "日付": post_date,
                                    "時間": post_time,
                                    "チャンネル名": item["channel"],
                                })
                    if unmatched_events:
                        st.warning(
                            f"⚠️ テンプレート未登録のイベントが{len(unmatched_events)}件あります。"
                            "新しいイベントの可能性があるため、内容を確認してください。"
                        )
                        st.dataframe(
                            unmatched_events,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "開催日": st.column_config.TextColumn("開催日", width="small"),
                                "開始時間": st.column_config.TextColumn("開始時間", width="small"),
                                "イベント名": st.column_config.TextColumn("イベント名", width="large"),
                            },
                        )
                        st.caption(
                            "💡 告知が必要なイベントは、Googleスプレッドシートの「テンプレート」タブへ追加し、"
                            "「スプレッドシートの変更をツールへ反映」を押してください。"
                        )
                    else:
                        st.success("✅ 取得したイベントはすべてテンプレートに登録されています。")
                    if rows:
                        import io
                        import csv as csv_module
                        st.success(f"{len(rows)}件の告知文を生成しました。")
                        st.dataframe(rows, use_container_width=True, height=400, column_config={"メッセージ": st.column_config.TextColumn("メッセージ", width="large")})
                        buf = io.StringIO()
                        w = csv_module.writer(buf)
                        w.writerow(["メッセージ", "日付", "時間", "チャンネル名"])
                        for r in rows:
                            w.writerow([r["メッセージ"], r["日付"], r["時間"], r["チャンネル名"]])
                        csv_str = buf.getvalue()
                        st.download_button(
                            "📥 CSVをダウンロード（A=メッセージ, B=日付, C=時間, D=チャンネル名）",
                            csv_str.encode("utf-8-sig"),
                            file_name="告知文一覧.csv",
                            mime="text/csv; charset=utf-8",
                            key="dl_bulk_csv",
                        )
                        st.caption("💡 当日告知＝開催当日08:00。事前告知＝前日18:00。まもなく開始＝開始15分前。A列=メッセージ, B列=日付(投稿日), C列=時間(投稿時間), D列=チャンネル名。")
                    else:
                        st.warning("生成できる予定がありませんでした。")

                st.divider()
                st.markdown("**月全体の案内文を生成**")
                if st.button("📅 月全体の案内文を生成", type="primary", key="btn_monthly"):
                    ev_clean = [_apply_template_keyword_match(ed) for ed in events_list]
                    for ed in ev_clean:
                        for k in ("_id", "_raw_summary", "_raw_description"):
                            ed.pop(k, None)
                    try:
                        from datetime import datetime as dt
                        if ev_clean and ev_clean[0].get("date"):
                            parts = str(ev_clean[0]["date"]).strip().split("/")
                            month_str = f"{int(parts[0])}月" if parts else f"{dt.now().month}月"
                        else:
                            month_str = f"{dt.now().month}月"
                        overview = build_monthly_overview(ev_clean, month_str)
                        st.success("月全体の案内文を生成しました！")
                        st.text_area(
                            "月全体の案内文（コピーしてDiscordに貼り付けてください）",
                            overview,
                            height=500,
                            key="monthly_overview_output",
                        )
                        st.caption("💡 その他ジャンル→オン会→特別講義→講師対談→生徒対談→ジャンル特化グルコン（ジャンルごと・日付順）")
                    except Exception as e:
                        st.error(f"エラー: {e}")
    tab_idx += 1

with tabs[tab_idx]:
    st.markdown("**イベント情報を手動で入力**")
    _template_records_for_select = _load_template_records()
    _event_type_options = sorted(set([rec["event_type"] for rec in _template_records_for_select])) or [
                "ジャンル特化グルコン（事前告知）", "ジャンル特化グルコン（間もなく開始）",
                "万垢生限定オン会（事前告知）", "万垢生限定オン会（間もなく開始）",
                "生徒対談（事前告知）", "生徒対談（間もなく開始）",
                "講師対談（事前告知）", "講師対談（間もなく開始）",
                "オン会（事前告知）", "オン会（間もなく開始）",
            ]
    col1, col2 = st.columns(2)
    with col1:
        manual_event_type = st.selectbox(
            "イベント種別",
            _event_type_options,
        )
        manual_date = st.text_input("開催日", placeholder="例: 1/31")
        manual_time = st.text_input("開始時間", placeholder="例: 12:00")
    with col2:
        manual_genre = st.text_input("ジャンル（グルコンの場合）", placeholder="例: レシピジャンル")
        manual_teacher = st.text_input("講師名", placeholder="例: アカウント名")
        manual_instagram = st.text_input("Instagramリンク", placeholder="https://www.instagram.com/...")

tab_idx += 1
with tabs[tab_idx]:
    st.markdown("**📝 テンプレート管理**")
    st.caption("テンプレートの追加・修正・削除はGoogleスプレッドシートで行い、変更後に「ツールへ反映」を押してください。自動更新は行いません。")

    link_col, sync_col = st.columns([1, 1])
    with link_col:
        st.markdown(f"[📊 Googleスプレッドシートを開く]({TEMPLATE_SHEET_URL})")
    with sync_col:
        if st.button("🔄 スプレッドシートの変更をツールへ反映", type="primary", use_container_width=True):
            try:
                creds_dict = st.session_state.get("google_credentials")
                if not creds_dict:
                    raise RuntimeError("先に「Googleカレンダーと連携」からGoogleに連携してください。")
                creds = dict_to_credentials(creds_dict)
                creds, updated = refresh_credentials_if_needed(creds)
                if updated:
                    st.session_state["google_credentials"] = updated
                synced_count = _sync_templates_from_google_sheet(creds)
                updated_at = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")
                st.session_state["template_sheet_synced_at"] = updated_at
                st.session_state["template_sheet_sync_message"] = (
                    f"テンプレートと判定ルールを{synced_count}件反映しました。"
                )
                st.session_state["template_sheet_auto_loaded"] = True
                st.session_state.pop("template_sheet_auto_error", None)
                st.rerun()
            except Exception as e:
                st.error(f"スプレッドシートの反映に失敗しました: {e}")

    if st.session_state.get("template_sheet_synced_at"):
        message = st.session_state.get("template_sheet_sync_message", "")
        st.info(f"{message} 最終反映：{st.session_state['template_sheet_synced_at']}")
    if st.session_state.get("template_sheet_auto_error"):
        st.warning(
            "リロード時の自動取得に失敗しました。Google連携を確認して、"
            "「スプレッドシートの変更をツールへ反映」を押してください。\n\n"
            f"詳細: {st.session_state['template_sheet_auto_error']}"
        )

    st.markdown(
        "**スプレッドシートの列**  \n"
        "A列 `event_type`：イベント種別名　/　"
        "B列 `template`：メッセージ本文　/　"
        "C列 `channels`：配信先（複数はカンマ区切り）　/　"
        "D列 `match_keywords`：判定キーワード（カンマ区切りはAND、`|`区切りはOR）"
    )

    st.caption(
        "例：フォロワー別グルコンは `フォロワー別,グルコン`、通常のグルコンは `グルコン`。"
        "複数キーワードのルールが自動的に優先されます。"
    )

    template_records = _load_template_records()
    st.subheader("現在ツールに反映中のテンプレート")
    if template_records:
        for i, rec in enumerate(template_records):
            event_type = rec["event_type"]
            body = rec["template"]
            channels = rec.get("channels", "")
            match_keywords = rec.get("match_keywords", "") or "（設定なし）"
            with st.expander(f"**{event_type}**｜配信先：{channels}"):
                st.caption(f"判定キーワード：{match_keywords}")
                st.text_area("本文プレビュー", body, height=240, key=f"preview_{i}", disabled=True)
    else:
        st.warning("反映中のテンプレートがありません。")

    st.subheader("CSVでダウンロード")
    if template_records:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=TEMPLATE_CSV_FIELDS)
        w.writeheader()
        for rec in template_records:
            w.writerow(rec)
        csv_bytes = buf.getvalue().encode("utf-8-sig")
        st.download_button("現在のテンプレート一式をCSVでダウンロード", csv_bytes, file_name="templates.csv", mime="text/csv; charset=utf-8", key="dl_templates_csv")
        st.caption("バックアップ用です。通常の編集・追加・削除はGoogleスプレッドシートで行います。")

if st.button("📝 告知文を生成", type="primary", key="btn_generate"):
    event_data = {
        "event_type": manual_event_type,
        "date": manual_date,
        "time": manual_time,
    }
    if manual_genre:
        event_data["genre"] = manual_genre
    if manual_teacher:
        event_data["teacher_name"] = manual_teacher
    if manual_instagram:
        event_data["instagram_url"] = manual_instagram
    if not manual_date or not manual_time:
        st.warning("開催日と開始時間は必須です")
        event_data = None

    if event_data:
        try:
            generator = AnnouncementGenerator()
            is_valid, errors = generator.validate_event_data(event_data)
            if not is_valid:
                st.warning("入力情報に不備があります")
                for err in errors:
                    st.write(f"• {err}")
            else:
                items = _generate_announcement_items(generator, event_data)
                if items:
                    st.success("告知文を生成しました！")
                    for item_idx, item in enumerate(items):
                        st.text_area(
                            f"生成された告知文｜配信先：{item['channel']}",
                            item["message"],
                            height=400,
                            key=f"announcement_output_{item_idx}",
                        )
                    st.caption("💡 上のテキストを選択して Ctrl+C（Mac: Cmd+C）でコピーできます")
                else:
                    st.error("告知文の生成に失敗しました")
        except Exception as e:
            st.error(f"エラー: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()
st.markdown("""
**利用可能なテンプレート**
- ジャンル特化グルコン（当日告知）
- 万垢生限定オン会（当日告知）
- 生徒対談（当日告知）
- 講師対談（当日告知）
- オン会（当日告知）
- 月全体の案内文（Googleカレンダー連携タブで「月全体の案内文を生成」）
- **テンプレート管理**タブで特別講義など新しい種別を追加できます
""")
