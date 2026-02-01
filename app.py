#!/usr/bin/env python3
"""
Discordオンラインイベント配信文章 自動生成ツール - Web版

使い方:
    streamlit run app.py
"""

import streamlit as st
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parse_calendar import parse_calendar_text, parse_event_name
from generate_announcement import AnnouncementGenerator

# Googleカレンダー連携（オプション）
try:
    from google_calendar_client import (
        GOOGLE_API_AVAILABLE,
        get_authorization_url,
        exchange_code_for_credentials,
        credentials_to_dict,
        dict_to_credentials,
        refresh_credentials_if_needed,
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

def _handle_oauth_callback():
    q = st.query_params
    code = q.get("code")
    if code and isinstance(code, list):
        code = code[0]
    if not code:
        return
    # 既に連携済みでURLにcodeだけ残っている場合：URLを掃除して再表示
    if "google_credentials" in st.session_state:
        try:
            st.query_params.clear()
        except Exception:
            for key in list(st.query_params.keys()):
                try:
                    del st.query_params[key]
                except Exception:
                    pass
        st.rerun()
        return
    redirect_uri = os.environ.get("REDIRECT_URI") or (
        st.secrets.get("REDIRECT_URI") if hasattr(st, "secrets") else None
    ) or "http://localhost:8501"
    try:
        creds = exchange_code_for_credentials(redirect_uri, code)
    except Exception as e:
        st.session_state["oauth_error"] = str(e)
        st.rerun()
        return
    if creds:
        st.session_state["google_credentials"] = credentials_to_dict(creds)
        st.session_state["oauth_just_completed"] = True
        if "oauth_error" in st.session_state:
            del st.session_state["oauth_error"]
        try:
            st.query_params.clear()
        except Exception:
            for key in list(st.query_params.keys()):
                try:
                    del st.query_params[key]
                except Exception:
                    pass
        st.rerun()
    else:
        st.session_state["oauth_error"] = "トークンの取得に失敗しました。もう一度「Googleカレンダーと連携する」からやり直してください。"
        st.rerun()

if GOOGLE_API_AVAILABLE:
    _handle_oauth_callback()

tab_names = ["🔗 Googleカレンダーと連携", "📋 貼り付けで入力", "✏️ 手動入力"]
if not GOOGLE_API_AVAILABLE:
    tab_names = ["📋 貼り付けで入力", "✏️ 手動入力"]

tabs = st.tabs(tab_names)
tab_idx = 0

if GOOGLE_API_AVAILABLE:
    with tabs[tab_idx]:
        redirect_uri = os.environ.get("REDIRECT_URI") or (
            st.secrets.get("REDIRECT_URI") if hasattr(st, "secrets") else None
        ) or "http://localhost:8501"
        auth_url = get_authorization_url(redirect_uri)

        if "oauth_error" in st.session_state:
            st.error(st.session_state["oauth_error"])
            if st.button("エラーを消す"):
                del st.session_state["oauth_error"]
                st.rerun()
        if "google_credentials" not in st.session_state:
            st.markdown("**Googleカレンダーと連携して、予定を自動で取り込みます**")
            if auth_url:
                # 同じタブで開く（許可後にこのタブに戻り、連携済みが表示されるようにする）
                st.markdown(
                    f'<a href="{auth_url}" style="display:inline-block;padding:0.5rem 1rem;'
                    'background:#FF4B4B;color:white;text-decoration:none;border-radius:0.5rem;font-weight:500;">'
                    '🔗 Googleカレンダーと連携する</a>',
                    unsafe_allow_html=True,
                )
                st.caption("クリックしてGoogleでログインし、許可するとこのページに戻り「連携済み」と表示されます。")
                # 設定確認（redirect_uri_mismatch の診断用）
                with st.expander("🔧 redirect_uri_mismatch が出る場合の確認"):
                    st.code(redirect_uri, language=None)
                    st.markdown("""
**上記のURLが以下と完全に一致しているか確認してください：**

1. **ブラウザのアドレスバー**：今開いているこのページのURL（`https://〇〇〇.streamlit.app`）
2. **Google Cloud**：認証情報 → OAuthクライアントID → 承認済みのリダイレクトURI
3. **Streamlit Secrets**：`REDIRECT_URI` の値

`http://localhost:8501` と表示されている場合、Streamlit Cloud の **Settings → Secrets** で
`REDIRECT_URI = "https://あなたのアプリURL.streamlit.app"` を追加してください。
                    """)
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
                st.rerun()

            if st.button("📅 予定を取得"):
                with st.spinner("予定を取得しています..."):
                    try:
                        creds, updated = refresh_credentials_if_needed(creds)
                        if updated is not None:
                            st.session_state["google_credentials"] = updated
                        events = fetch_upcoming_events(creds, max_results=30, days_ahead=14)
                        event_data_list = []
                        for ev in events:
                            if ev.get("summary"):
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
                        generator = AnnouncementGenerator()
                        is_valid, errors = generator.validate_event_data(ed)
                        if not is_valid:
                            st.warning("入力情報に不備があります（手動で補完するか、貼り付け入力をお試しください）")
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
    tab_idx += 1

with tabs[tab_idx]:
    st.markdown("""
    **Googleカレンダーの予定をコピー＆ペーストしてください**
    
    以下のような形式で入力：
    ```
    【ジャンル特化グルコン】よだれ夫婦講師（レシピジャンル）
    1月 31日 (土曜日)⋅午後12:00～1:00
    Instagramリンク：https://www.instagram.com/yurina_diet.recipe
    Zoomリンク：https://us06web.zoom.us/j/...
    ミーティング ID: 867 8339 1679
    パスコード: 0000
    ```
    """)
    calendar_text = st.text_area(
        "カレンダー情報を貼り付け",
        height=200,
        placeholder="ここにGoogleカレンダーの予定を貼り付けてください...",
        label_visibility="collapsed",
    )
tab_idx += 1

with tabs[tab_idx]:
    st.markdown("**イベント情報を手動で入力**")
    col1, col2 = st.columns(2)
    with col1:
        manual_event_type = st.selectbox(
            "イベント種別",
            [
                "ジャンル特化グルコン（事前告知）",
                "ジャンル特化グルコン（間もなく開始）",
                "ジャンル特化グルコン（卒業生向け）",
                "生徒対談（事前告知）",
                "生徒対談（間もなく開始）",
                "講師対談（事前告知）",
                "講師対談（間もなく開始）",
                "オン会（事前告知）",
                "オン会（間もなく開始）",
            ],
        )
        manual_date = st.text_input("開催日", placeholder="例: 1/31")
        manual_time = st.text_input("開始時間", placeholder="例: 12:00")
    with col2:
        manual_genre = st.text_input("ジャンル（グルコンの場合）", placeholder="例: レシピジャンル")
        manual_teacher = st.text_input("講師名", placeholder="例: よだれ夫婦")
        manual_instagram = st.text_input("Instagramリンク", placeholder="https://www.instagram.com/...")

if st.button("📝 告知文を生成", type="primary", key="btn_generate"):
    event_data = None
    if calendar_text.strip():
        try:
            event_data = parse_calendar_text(calendar_text)
            required = ['date', 'time', 'event_type']
            missing = [f for f in required if f not in event_data]
            if missing:
                st.warning(f"以下の情報が不足しています: {', '.join(missing)}")
                st.json(event_data)
                event_data = None
        except Exception as e:
            st.error(f"パースエラー: {e}")
            event_data = None
    else:
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
- ジャンル特化グルコン（事前告知 / 間もなく開始 / 卒業生向け）
- 生徒対談（事前告知 / 間もなく開始）
- 講師対談（事前告知 / 間もなく開始）
- オン会（事前告知 / 間もなく開始）
""")
