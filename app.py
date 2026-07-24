#!/usr/bin/env python3
"""
Discordオンラインイベント配信文章 自動生成ツール - Web版

使い方:
    streamlit run app.py
"""

import streamlit as st
import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_calendar import parse_event_name
from generate_announcement import AnnouncementGenerator
from monthly_overview import build_monthly_overview
from config import CALENDAR_EXCLUDE_TITLES
from google.oauth2.credentials import Credentials

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
]
GOOGLE_SCOPE_STR = " ".join(GOOGLE_SCOPE_LIST)


def _use_streamlit_oauth() -> bool:
    if not STREAMLIT_OAUTH_AVAILABLE:
        return False
    if not hasattr(st, "secrets"):
        return False
    return bool(st.secrets.get("GOOGLE_CLIENT_ID") and st.secrets.get("GOOGLE_CLIENT_SECRET"))


def _get_channel_name(event_type: str) -> str:
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


def _get_channel_names(event_type: str) -> list[str]:
    """イベント種別に応じた配信先一覧を返す"""
    if "万垢生限定オン会" in str(event_type) or "万垢" in str(event_type):
        return ["万垢お知らせチャンネル", "講師お知らせ", "専属講師チーム"]
    return [_get_channel_name(event_type)]


def _get_post_date_time(event_type: str, event_date: str, event_time: str):
    """
    当日告知＝開催当日 08:00 固定を返す。
    戻り値: (日付文字列 "M/D", 時間文字列 "HH:MM")
    """
    from datetime import datetime
    year = datetime.now().year
    try:
        parts = str(event_date).strip().split("/")
        if len(parts) >= 2:
            m, d = int(parts[0]), int(parts[1])
            return (f"{m}/{d}", "08:00")
        return (event_date, "08:00")
    except Exception:
        return (event_date, "08:00")


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

tab_names = ["🔗 Googleカレンダーと連携", "✏️ 手動入力", "📝 テンプレート管理"]
if not GOOGLE_API_AVAILABLE:
    tab_names = ["✏️ 手動入力", "📝 テンプレート管理"]

tabs = st.tabs(tab_names)
tab_idx = 0

if "custom_templates" not in st.session_state:
    st.session_state["custom_templates"] = {}

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
                    ed = events_list[selected].copy()
                    for k in ("_id", "_raw_summary", "_raw_description"):
                        ed.pop(k, None)
                    try:
                        generator = AnnouncementGenerator(templates_override=st.session_state.get("custom_templates", {}))
                        is_valid, errors = generator.validate_event_data(ed)
                        if not is_valid:
                            st.warning("入力情報に不備があります（手動入力タブで補完してください）")
                            for err in errors:
                                st.write(f"• {err}")
                        else:
                            announcement = generator.generate(ed)
                            if announcement:
                                st.success("告知文を生成しました！")
                                st.text_area(
                                    "生成された告知文（コピーしてDiscordに貼り付けてください）",
                                    announcement,
                                    height=400,
                                    key="announcement_output_linked",
                                )
                                st.caption("💡 上のテキストを選択して Ctrl+C（Mac: Cmd+C）でコピーできます")
                            else:
                                st.error("告知文の生成に失敗しました")
                    except Exception as e:
                        st.error(f"エラー: {e}")

                st.divider()
                st.markdown("**1ヶ月分を一括生成してスプレッドシート用に出力**")
                if st.button("📋 1ヶ月分の告知文を一括生成", type="primary", key="btn_bulk"):
                    generator = AnnouncementGenerator(templates_override=st.session_state.get("custom_templates", {}))
                    rows = []
                    for ed in events_list:
                        ev_copy = ed.copy()
                        for k in ("_id", "_raw_summary", "_raw_description"):
                            ev_copy.pop(k, None)
                        # 1件の予定につき「当日告知」1行を出力（開催当日 08:00）
                        if "（事前告知）" in (ev_copy.get("event_type") or ""):
                            ev_copy["event_type"] = ev_copy["event_type"].replace("（事前告知）", "（当日告知）")
                        if "（間もなく開始）" in (ev_copy.get("event_type") or ""):
                            ev_copy["event_type"] = ev_copy["event_type"].replace("（間もなく開始）", "（当日告知）")
                        row_type = ev_copy.get("event_type", "")
                        post_date, post_time = _get_post_date_time(
                            row_type, ev_copy.get("date", ""), ev_copy.get("time", "")
                        )
                        is_valid = generator.validate_event_data(ev_copy)[0]
                        if not is_valid:
                            continue
                        ann = generator.generate(ev_copy) or ""
                        msg = (ann or "").replace("\r", "\n")
                        for channel_name in _get_channel_names(row_type):
                            rows.append({
                                "メッセージ": msg,
                                "日付": post_date,
                                "時間": post_time,
                                "チャンネル名": channel_name,
                            })
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
                        st.caption("💡 当日告知＝開催当日08:00。A列=メッセージ, B列=日付(投稿日), C列=時間(投稿時間), D列=チャンネル名。")
                    else:
                        st.warning("生成できる予定がありませんでした。")

                st.divider()
                st.markdown("**月全体の案内文を生成**")
                if st.button("📅 月全体の案内文を生成", type="primary", key="btn_monthly"):
                    ev_clean = [ed.copy() for ed in events_list]
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
    _gen = AnnouncementGenerator(templates_override=st.session_state.get("custom_templates", {}))
    _event_type_options = sorted(_gen.templates.keys()) or [
                "ジャンル特化グルコン（当日告知）",
                "万垢生限定オン会（当日告知）",
                "生徒対談（当日告知）",
                "講師対談（当日告知）",
                "オン会（当日告知）",
            ]
    col1, col2 = st.columns(2)
    with col1:
        manual_event_type = st.selectbox(
            "イベント種別",
            _event_type_options,
            format_func=lambda x: x + " ※追加" if x in st.session_state.get("custom_templates", {}) else x,
        )
        manual_date = st.text_input("開催日", placeholder="例: 1/31")
        manual_time = st.text_input("開始時間", placeholder="例: 12:00")
    with col2:
        manual_genre = st.text_input("ジャンル（グルコンの場合）", placeholder="例: レシピジャンル")
        manual_teacher = st.text_input("講師名", placeholder="例: アカウント名")
        manual_instagram = st.text_input("Instagramリンク", placeholder="https://www.instagram.com/...")

tab_idx += 1
with tabs[tab_idx]:
    st.markdown("**📝 テンプレートの追加・編集**")
    st.caption("現在のテンプレートを一覧表示し、編集できます。追加・編集した内容はこのセッション中のみ有効です。永続化する場合は「CSVでダウンロード」して templates/templates.csv に反映してください。")
    custom = st.session_state.get("custom_templates", {})
    base_gen = AnnouncementGenerator()
    all_templates = {**base_gen.templates, **custom}

    st.subheader("現在使用中のテンプレート一覧")
    if "editing_template" not in st.session_state:
        st.session_state["editing_template"] = None
    editing = st.session_state.get("editing_template")

    if all_templates:
        for i, (event_type, body) in enumerate(sorted(all_templates.items())):
            is_custom = event_type in custom
            with st.expander(f"**{event_type}**" + (" ※編集済み" if is_custom else ""), expanded=(editing == event_type)):
                if editing == event_type:
                    new_body = st.text_area("テンプレート本文を編集", body, height=250, key=f"edit_body_{i}")
                    col1, col2, _ = st.columns([1, 1, 2])
                    with col1:
                        if st.button("保存", key=f"save_edit_{i}"):
                            custom[event_type] = new_body
                            st.session_state["custom_templates"] = custom
                            st.session_state["editing_template"] = None
                            st.rerun()
                    with col2:
                        if st.button("キャンセル", key=f"cancel_edit_{i}"):
                            st.session_state["editing_template"] = None
                            st.rerun()
                    if is_custom:
                        if st.button("このテンプレートを削除", key=f"del_edit_{i}"):
                            del custom[event_type]
                            st.session_state["custom_templates"] = custom
                            st.session_state["editing_template"] = None
                            st.rerun()
                else:
                    st.text_area("本文", body[:500] + ("..." if len(body) > 500 else ""), height=120, key=f"preview_{i}", disabled=True)
                    if st.button("編集", key=f"btn_edit_{i}"):
                        st.session_state["editing_template"] = event_type
                        st.rerun()
                    if is_custom:
                        if st.button("デフォルトに戻す", key=f"reset_{i}"):
                            del custom[event_type]
                            st.session_state["custom_templates"] = custom
                            st.rerun()
    else:
        st.info("テンプレートがありません。下の「テンプレートを追加」で追加してください。")

    st.subheader("テンプレートを追加")
    with st.form("add_template_form", clear_on_submit=True):
        new_event_type = st.text_input("イベント種別名", placeholder="例: 特別講義（当日告知）")
        new_template = st.text_area("テンプレート本文", placeholder="@everyone\n\n## 明日{{date}}の{{time}}より特別講義が開催されます...\n\n利用可能な変数: {{date}}, {{time}}, {{teacher_name}}, {{instagram_url}}, {{zoom_url}}, {{genre}} など", height=200)
        if st.form_submit_button("追加"):
            if new_event_type and new_template:
                custom[new_event_type.strip()] = new_template.strip()
                st.session_state["custom_templates"] = custom
                st.success(f"「{new_event_type.strip()}」を追加しました。")
                st.rerun()
            else:
                st.warning("イベント種別名とテンプレート本文を入力してください。")

    st.subheader("CSVでダウンロード")
    if all_templates:
        import io
        import csv as csv_module
        buf = io.StringIO()
        w = csv_module.writer(buf)
        w.writerow(["event_type", "template"])
        for et, tmpl in sorted(all_templates.items()):
            w.writerow([et, tmpl])
        csv_bytes = buf.getvalue().encode("utf-8-sig")
        st.download_button("現在のテンプレート一式をCSVでダウンロード", csv_bytes, file_name="templates.csv", mime="text/csv; charset=utf-8", key="dl_templates_csv")
        st.caption("ダウンロードしたCSVを templates/templates.csv に置き換えると、次回以降もその内容がデフォルトになります。")

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
            generator = AnnouncementGenerator(templates_override=st.session_state.get("custom_templates", {}))
            is_valid, errors = generator.validate_event_data(event_data)
            if not is_valid:
                st.warning("入力情報に不備があります")
                for err in errors:
                    st.write(f"• {err}")
            else:
                announcement = generator.generate(event_data)
                if announcement:
                    st.success("告知文を生成しました！")
                    st.text_area(
                        "生成された告知文（コピーしてDiscordに貼り付けてください）",
                        announcement,
                        height=400,
                        key="announcement_output",
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
