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
import hashlib
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
from calendar_image import (
    DEFAULT_CATEGORY_STYLES,
    classify_event,
    event_display_text,
    fetch_instagram_profile_image,
    generate_calendar_image,
)
from config import CALENDAR_EXCLUDE_TITLES
from google.oauth2.credentials import Credentials

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_CSV_PATH = os.path.join(APP_DIR, "templates", "templates.csv")
TEMPLATE_CSV_FIELDS = ["event_type", "template", "channels", "match_keywords", "delivery_time"]
TEMPLATE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1d2BkB9xIQZnFVdiV7Bk-x3S2yA7XAmAgUPa79iLJrTo/edit?usp=sharing"
TEMPLATE_SHEET_ID = "1d2BkB9xIQZnFVdiV7Bk-x3S2yA7XAmAgUPa79iLJrTo"
TEMPLATE_SHEET_GID = "0"
TEMPLATE_SHEET_RANGE = "テンプレート!A:E"
CALENDAR_ASSET_DIR = os.path.join(APP_DIR, "calendar_assets")
CALENDAR_IMAGE_LIBRARY_DIR = os.path.join(CALENDAR_ASSET_DIR, "image_library")
CALENDAR_IMAGE_LIBRARY_LIMIT = 300

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


@st.cache_data(ttl=86400, show_spinner=False)
def _cached_instagram_profile_image(instagram_url: str):
    """Instagram画像を1日キャッシュし、画像生成時の待ち時間を抑える。"""
    return fetch_instagram_profile_image(instagram_url)


def _save_calendar_asset(category: str, uploaded_file) -> str:
    """アップロード画像を再利用用の履歴に保存する。"""
    data = uploaded_file.getvalue()
    if not data:
        return ""
    os.makedirs(CALENDAR_ASSET_DIR, exist_ok=True)
    original = os.path.basename(uploaded_file.name or "image.png")
    safe_name = re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-鿿._-]+", "_", original)
    digest = hashlib.sha256(data).hexdigest()[:12]
    filename = f"{category}__{digest}__{safe_name}"
    path = os.path.join(CALENDAR_ASSET_DIR, filename)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return path


def _list_calendar_assets(category: str) -> list[tuple[str, str]]:
    if not os.path.isdir(CALENDAR_ASSET_DIR):
        return []
    prefix = f"{category}__"
    assets = []
    for filename in sorted(os.listdir(CALENDAR_ASSET_DIR), reverse=True):
        if not filename.startswith(prefix):
            continue
        path = os.path.join(CALENDAR_ASSET_DIR, filename)
        if not os.path.isfile(path):
            continue
        parts = filename.split("__", 2)
        label = parts[2] if len(parts) == 3 else filename
        assets.append((label, path))
    return assets


def _read_saved_asset(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def _list_image_library() -> list[tuple[str, str]]:
    """共通画像ライブラリを最終使用日時の新しい順で返す。"""
    if not os.path.isdir(CALENDAR_IMAGE_LIBRARY_DIR):
        return []
    assets = []
    for filename in os.listdir(CALENDAR_IMAGE_LIBRARY_DIR):
        path = os.path.join(CALENDAR_IMAGE_LIBRARY_DIR, filename)
        if not os.path.isfile(path):
            continue
        parts = filename.split("__", 1)
        label = parts[1] if len(parts) == 2 else filename
        assets.append((label, path))
    assets.sort(key=lambda item: os.path.getmtime(item[1]), reverse=True)
    return assets[:CALENDAR_IMAGE_LIBRARY_LIMIT]


def _save_image_library_asset(uploaded_file) -> tuple[str, str]:
    """画像を共通ライブラリへ保存する。重複画像は再利用する。"""
    data = uploaded_file.getvalue()
    if not data:
        return "", "画像データが空です。"
    os.makedirs(CALENDAR_IMAGE_LIBRARY_DIR, exist_ok=True)
    original = os.path.basename(uploaded_file.name or "image.png")
    safe_name = re.sub(r"[^0-9A-Za-zぁ-んァ-ン一-鿿._-]+", "_", original)
    digest = hashlib.sha256(data).hexdigest()[:16]
    existing = next(
        (path for _, path in _list_image_library() if os.path.basename(path).startswith(f"{digest}__")),
        "",
    )
    if existing:
        os.utime(existing, None)
        return existing, ""
    if len(_list_image_library()) >= CALENDAR_IMAGE_LIBRARY_LIMIT:
        return "", f"画像ライブラリは最大{CALENDAR_IMAGE_LIBRARY_LIMIT}件です。不要な画像を削除してください。"
    path = os.path.join(CALENDAR_IMAGE_LIBRARY_DIR, f"{digest}__{safe_name}")
    with open(path, "wb") as f:
        f.write(data)
    return path, ""


def _touch_image_library_asset(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.utime(path, None)
    except OSError:
        pass


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
    """テンプレートCSVからテンプレート本文・判定条件・配信タイミングを読み込む"""
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
                    "delivery_time": (row.get("delivery_time") or "").strip(),
                })
    except Exception as e:
        st.error(f"テンプレートCSVの読み込みに失敗しました: {e}")
    return records


def _parse_template_csv(text: str) -> list[dict]:
    """Googleスプレッドシートから取得したCSVを検証する"""
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fieldnames = [str(name or "").strip() for name in (reader.fieldnames or [])]
    required = {"event_type", "template", "channels", "match_keywords", "delivery_time"}
    missing = required - set(fieldnames)
    if missing:
        raise ValueError(
            "1行目に event_type, template, channels, match_keywords, delivery_time の5列が必要です。"
            f" 不足: {', '.join(sorted(missing))}"
        )

    records = []
    for row_number, row in enumerate(reader, start=2):
        event_type = (row.get("event_type") or "").strip()
        template = (row.get("template") or "").strip()
        channels = (row.get("channels") or "").strip()
        match_keywords = (row.get("match_keywords") or "").strip()
        delivery_time = (row.get("delivery_time") or "").strip()
        if not event_type and not template and not channels and not match_keywords and not delivery_time:
            continue
        if not event_type or not template:
            raise ValueError(f"{row_number}行目: event_type と template は必須です。")
        records.append({
            "event_type": event_type,
            "template": template,
            "channels": channels or _join_channels(_get_default_channel_names(event_type)),
            "match_keywords": match_keywords,
            "delivery_time": delivery_time,
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
            "delivery_time": rec.get("delivery_time", "").strip(),
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
                        "delivery_time": (rec.get("delivery_time") or "").strip(),
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
                items.append({
                    "message": msg,
                    "channel": channel,
                    "delivery_time": (rec.get("delivery_time") or "").strip(),
                })
    else:
        msg = generator.generate(event_data)
        if msg:
            for channel in _get_default_channel_names(event_type):
                items.append({"message": msg, "channel": channel, "delivery_time": ""})
    return items


def _get_post_date_time(event_type: str, event_date: str, event_time: str, delivery_time: str = ""):
    """
    delivery_time があればスプレッドシート設定を優先する。
    対応形式: HH:MM / 当日HH:MM / 前日HH:MM / 15分前 / 開始15分前。
    空欄の場合は従来どおりイベント種別から判定する。
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
        event_dt = datetime(year, m, d)
        setting = re.sub(r"\s+", "", str(delivery_time or "").strip())
        relative_match = re.fullmatch(r"(?:開始)?(\d+)分前", setting)
        fixed_match = re.fullmatch(r"(?:(前日|当日))?(\d{1,2}):(\d{2})", setting)
        if relative_match:
            t = str(event_time).strip()
            if ":" in t:
                h, mi = [int(v) for v in t.split(":", 1)]
                post_dt = datetime(year, m, d, h, mi) - timedelta(minutes=int(relative_match.group(1)))
                return (f"{post_dt.month}/{post_dt.day}", f"{post_dt.hour:02d}:{post_dt.minute:02d}")
        elif fixed_match:
            day_label, hour, minute = fixed_match.groups()
            post_dt = event_dt - timedelta(days=1 if day_label == "前日" else 0)
            return (f"{post_dt.month}/{post_dt.day}", f"{int(hour):02d}:{int(minute):02d}")

        if "当日告知" in str(event_type):
            post_date_str = f"{m}/{d}"
            post_time_str = "08:00"
        elif "事前告知" in str(event_type):
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

tab_names = ["🔗 Googleカレンダーと連携", "🖼️ カレンダー画像", "✏️ 手動入力", "📝 テンプレート管理"]
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
                if "calendar_image_events" in st.session_state:
                    del st.session_state["calendar_image_events"]
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
                        calendar_image_event_list = []
                        for ev in events:
                            summary = (ev.get("summary") or "").strip()
                            if not summary:
                                continue
                            ed = api_event_to_event_data(ev, parse_event_name)
                            ed["_id"] = ev.get("id", "")
                            ed = _apply_template_keyword_match(ed)
                            # カレンダー画像には週報提出を含む全予定を保持する。
                            calendar_image_event_list.append(ed)
                            # 告知文・月全体案内では従来どおり除外設定を適用する。
                            if any(exc in summary for exc in CALENDAR_EXCLUDE_TITLES):
                                continue
                            event_data_list.append(ed)
                        st.session_state["calendar_events"] = event_data_list
                        st.session_state["calendar_image_events"] = calendar_image_event_list
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
                            is_valid = generator.validate_event_data(ev_row)[0]
                            if not is_valid:
                                continue
                            items = _generate_announcement_items(generator, ev_row)
                            for item in items:
                                post_date, post_time = _get_post_date_time(
                                    row_type,
                                    ev_row.get("date", ""),
                                    ev_row.get("time", ""),
                                    item.get("delivery_time", ""),
                                )
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
        st.markdown("**🖼️ 1ヶ月分の予定からカレンダー画像を作成**")
        st.caption(
            "先に「Googleカレンダーと連携」タブで予定を取得してください。"
            "背景色とイラストは生成するたびに変更できます。"
        )

        calendar_events = st.session_state.get(
            "calendar_image_events", st.session_state.get("calendar_events", [])
        )
        if not calendar_events:
            st.info("予定がまだありません。Googleカレンダータブで「📅 予定を取得」を押してください。")
        else:
            first_date = str(calendar_events[0].get("date", "") or "")
            try:
                default_month = int(first_date.split("/")[0])
            except (ValueError, IndexError):
                default_month = datetime.now().month
            year_col, month_col = st.columns(2)
            with year_col:
                image_year = st.number_input("年", min_value=2020, max_value=2100, value=datetime.now().year, step=1)
            with month_col:
                image_month = st.number_input("月", min_value=1, max_value=12, value=default_month, step=1)

            month_events = []
            for event in calendar_events:
                try:
                    if int(str(event.get("date", "")).split("/")[0]) == int(image_month):
                        month_events.append(event)
                except (ValueError, IndexError):
                    continue

            st.write(f"**対象予定：{len(month_events)}件**")
            render_month_events = []
            event_images = {}
            event_image_paths = []
            if month_events:
                def calendar_event_key(event, event_index):
                    raw_key = str(event.get("_id") or (
                        f"{event.get('date', '')}|{event.get('time', '')}|"
                        f"{event.get('_raw_summary', '') or event.get('event_name', '')}|{event_index}"
                    ))
                    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]

                st.markdown("### 🖼️ 画像プレビュー編集")
                st.caption(
                    "予定を選択し、画像に表示する改行・文字と講師画像（またはイベント画像）を設定できます。"
                )
                target_key = f"calendar_text_edit_target_{int(image_year)}_{int(image_month)}"
                if target_key not in st.session_state or st.session_state[target_key] >= len(month_events):
                    st.session_state[target_key] = 0
                st.caption("編集したい予定をクリックしてください")
                preview_columns = st.columns(4)
                for event_index, event in enumerate(month_events):
                    event_label = (
                        f"{event.get('date', '')} {event.get('time', '')}\n"
                        f"{event.get('_raw_summary', '') or event.get('event_name', '')}"
                    )
                    with preview_columns[event_index % 4]:
                        if st.button(
                            event_label,
                            key=f"calendar_event_card_{int(image_year)}_{int(image_month)}_{event_index}",
                            type="primary" if st.session_state[target_key] == event_index else "secondary",
                            use_container_width=True,
                        ):
                            if st.session_state[target_key] != event_index:
                                st.session_state[target_key] = event_index
                                st.rerun()
                edit_index = int(st.session_state[target_key])
                selected_event = month_events[edit_index]
                selected_event_id = calendar_event_key(selected_event, edit_index)
                selected_text_key = (
                    f"calendar_display_text_{int(image_year)}_{int(image_month)}_{selected_event_id}"
                )
                selected_image_path_key = (
                    f"calendar_event_library_path_{int(image_year)}_{int(image_month)}_{selected_event_id}"
                )
                text_column, image_column = st.columns([3, 2])
                with text_column:
                    st.text_area(
                        "画像に表示する文字（改行も反映）",
                        value=event_display_text(selected_event),
                        height=180,
                        key=selected_text_key,
                    )
                with image_column:
                    uploaded_event_image = st.file_uploader(
                        "ライブラリへ画像を追加",
                        type=["png", "jpg", "jpeg", "webp"],
                        key=f"{selected_image_path_key}_uploader",
                        help=f"全予定で共通利用できます。最大{CALENDAR_IMAGE_LIBRARY_LIMIT}件です。",
                    )
                    if uploaded_event_image is not None:
                        saved_path, save_error = _save_image_library_asset(uploaded_event_image)
                        if save_error:
                            st.error(save_error)
                        elif saved_path:
                            st.session_state[selected_image_path_key] = saved_path
                            st.session_state[f"{selected_image_path_key}_selector"] = saved_path

                    library_assets = _list_image_library()
                    library_paths = [None] + [path for _, path in library_assets]
                    current_path = st.session_state.get(selected_image_path_key)
                    default_index = library_paths.index(current_path) if current_path in library_paths else 0
                    selected_library_path = st.selectbox(
                        f"画像ライブラリ（{len(library_assets)}/{CALENDAR_IMAGE_LIBRARY_LIMIT}件）",
                        library_paths,
                        index=default_index,
                        format_func=lambda path: "自動取得・カテゴリ画像を使用" if path is None else next(
                            (label for label, asset_path in library_assets if asset_path == path),
                            os.path.basename(path),
                        ),
                        key=f"{selected_image_path_key}_selector",
                    )
                    st.session_state[selected_image_path_key] = selected_library_path
                    if selected_library_path:
                        selected_image_data = _read_saved_asset(selected_library_path)
                        st.image(selected_image_data, caption="この予定に使用する画像", width=150)
                    else:
                        st.caption("画像未設定（Instagram画像またはカテゴリ画像を使用）")
                st.caption("予定を切り替えて編集してください。入力内容と画像は生成時に反映されます。")

                preview_rows = []
                for event_index, event in enumerate(month_events):
                    event_copy = event.copy()
                    event_id = calendar_event_key(event, event_index)
                    text_key = f"calendar_display_text_{int(image_year)}_{int(image_month)}_{event_id}"
                    image_path_key = f"calendar_event_library_path_{int(image_year)}_{int(image_month)}_{event_id}"
                    event_copy["_calendar_display_text"] = st.session_state.get(
                        text_key, event_display_text(event)
                    )
                    event_copy["_calendar_image_key"] = event_id
                    selected_path = st.session_state.get(image_path_key)
                    if selected_path:
                        image_data = _read_saved_asset(selected_path)
                        if image_data:
                            event_images[event_id] = image_data
                            event_image_paths.append(selected_path)
                    render_month_events.append(event_copy)
                    preview_rows.append({
                        "日付": event_copy.get("date", ""),
                        "時間": event_copy.get("time", ""),
                        "カテゴリ": classify_event(event_copy),
                        "カレンダー表示テキスト": event_copy.get("_calendar_display_text", ""),
                        "Instagram": event_copy.get("instagram_url", ""),
                    })
                st.dataframe(preview_rows, use_container_width=True, height=260)

                with st.expander("🗂️ 画像ライブラリを管理"):
                    st.caption("画像は最後に使用した順で表示されます。最大300件まで登録できます。")
                    management_assets = _list_image_library()
                    if not management_assets:
                        st.info("ライブラリに画像はまだありません。")
                    else:
                        management_path = st.selectbox(
                            "削除する画像を選択",
                            [path for _, path in management_assets],
                            format_func=lambda path: next(
                                (label for label, asset_path in management_assets if asset_path == path),
                                os.path.basename(path),
                            ),
                            key="calendar_library_delete_target",
                        )
                        st.image(_read_saved_asset(management_path), width=120)
                        if st.button("ライブラリから削除", key="calendar_library_delete_button"):
                            try:
                                os.remove(management_path)
                                for key, value in list(st.session_state.items()):
                                    if key.startswith("calendar_event_library_path_") and value == management_path:
                                        st.session_state[key] = None
                                st.success("画像を削除しました。")
                                st.rerun()
                            except OSError as e:
                                st.error(f"画像を削除できませんでした: {e}")

            st.markdown("**カテゴリ別の背景色**")
            category_colors = {}
            color_columns = st.columns(2)
            for idx, (category, default_color) in enumerate(DEFAULT_CATEGORY_STYLES.items()):
                with color_columns[idx % 2]:
                    category_colors[category] = st.color_picker(
                        category, default_color, key=f"calendar_color_{category}"
                    )

            category_illustrations = {}
            with st.expander("🎨 カテゴリ別イラスト（任意）"):
                st.caption(
                    "PNG・JPGを追加すると履歴に保存され、次回から選択だけで再利用できます。"
                    "カテゴリ画像は、講師画像が取得できない予定に使用します。"
                )

                asset_categories = list(DEFAULT_CATEGORY_STYLES)
                for category in asset_categories:
                    st.markdown(f"**{category}**")
                    history = _list_calendar_assets(category)
                    history_options = ["使用しない"] + [label for label, _ in history]
                    selected_history = st.selectbox(
                        f"{category}の履歴から選択",
                        history_options,
                        key=f"calendar_asset_history_{category}",
                    )
                    selected_data = None
                    if selected_history != "使用しない":
                        selected_index = history_options.index(selected_history) - 1
                        selected_data = _read_saved_asset(history[selected_index][1])

                    uploaded = st.file_uploader(
                        f"{category}の新しいイラストを追加",
                        type=["png", "jpg", "jpeg", "webp"],
                        key=f"calendar_illustration_{category}",
                    )
                    if uploaded is not None:
                        saved_path = _save_calendar_asset(category, uploaded)
                        selected_data = uploaded.getvalue()
                        if saved_path:
                            st.caption(f"✅ 履歴に保存済み：{uploaded.name}")

                    if selected_data:
                        category_illustrations[category] = selected_data

            use_instagram = st.checkbox(
                "Instagramリンクから講師アイコンの自動取得を試す",
                value=True,
                help="Instagram側の制限により取得できない場合は、カテゴリ別イラストへ自動で切り替わります。",
            )
            st.caption(
                "講師画像を取得するには、Googleカレンダー予定の説明欄へ講師のInstagramプロフィールURLを"
                "単独の行で入力し、予定を再取得してください。上の一覧の「Instagram」列にURLが表示されれば取得対象です。"
            )

            if st.button("🎨 カレンダー画像を生成", type="primary", disabled=not month_events):
                for used_image_path in set(event_image_paths):
                    _touch_image_library_asset(used_image_path)
                instagram_images = {}
                failed_instagram = 0
                if use_instagram:
                    instagram_urls = sorted({
                        str(event.get("instagram_url", "") or "").strip()
                        for event in render_month_events if event.get("instagram_url")
                    })
                    with st.spinner(f"Instagram画像を取得中…（0/{len(instagram_urls)}）"):
                        for instagram_url in instagram_urls:
                            image_data = _cached_instagram_profile_image(instagram_url)
                            if image_data:
                                instagram_images[instagram_url] = image_data
                            else:
                                failed_instagram += 1
                try:
                    png_data = generate_calendar_image(
                        render_month_events,
                        int(image_year),
                        int(image_month),
                        category_colors=category_colors,
                        category_illustrations=category_illustrations,
                        instagram_images=instagram_images,
                        event_images=event_images,
                    )
                    st.session_state["calendar_image_png"] = png_data
                    st.session_state["calendar_image_name"] = f"{int(image_year)}年{int(image_month)}月_わくわく予定カレンダー.png"
                    if failed_instagram:
                        st.warning(
                            f"Instagram画像は{failed_instagram}件取得できなかったため、"
                            "登録したイラストまたは画像なしで生成しました。"
                        )
                    st.success("カレンダー画像を生成しました。")
                except Exception as e:
                    st.error(f"画像の生成に失敗しました: {e}")

            if st.session_state.get("calendar_image_png"):
                st.image(st.session_state["calendar_image_png"], use_container_width=True)
                st.download_button(
                    "📥 PNG画像をダウンロード",
                    data=st.session_state["calendar_image_png"],
                    file_name=st.session_state.get("calendar_image_name", "calendar.png"),
                    mime="image/png",
                )
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
    st.caption("テンプレートの追加・修正・削除はGoogleスプレッドシートで行います。リロード時に最新版を自動取得し、すぐ反映したい場合は「ツールへ反映」を押してください。")

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
        "D列 `match_keywords`：判定キーワード（カンマ区切りはAND、`|`区切りはOR）　/　"
        "E列 `delivery_time`：配信タイミング"
    )

    st.caption(
        "例：フォロワー別グルコンは `フォロワー別,グルコン`、通常のグルコンは `グルコン`。"
        "複数キーワードのルールが自動的に優先されます。配信タイミングは `08:00`、"
        "`前日18:00`、`15分前` の形式で設定できます。"
    )

    template_records = _load_template_records()
    st.subheader("現在ツールに反映中のテンプレート")
    if template_records:
        for i, rec in enumerate(template_records):
            event_type = rec["event_type"]
            body = rec["template"]
            channels = rec.get("channels", "")
            match_keywords = rec.get("match_keywords", "") or "（設定なし）"
            delivery_time = rec.get("delivery_time", "") or "（イベント種別から自動判定）"
            with st.expander(f"**{event_type}**｜配信先：{channels}"):
                st.caption(f"判定キーワード：{match_keywords}")
                st.caption(f"配信タイミング：{delivery_time}")
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
