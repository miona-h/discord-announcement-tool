#!/usr/bin/env python3
"""
Discordオンラインイベント配信文章 自動生成ツール - Web版

使い方:
    streamlit run app.py

    または

    python -m streamlit run app.py
"""

import streamlit as st
import sys
import os

# プロジェクトルートをパスに追加
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


def _get_post_date_time(event_type: str, event_date: str, event_time: str):
    """
    事前告知＝前日18:00固定、まもなく開始＝当日開始5分前 を返す。
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
        if "事前告知" in str(event_type):
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
                t_dt = datetime(year, m, d, h, mi) - timedelta(minutes=5)
                post_time_str = f"{t_dt.hour:02d}:{t_dt.minute:02d}"
            else:
                post_time_str = t
        else:
            post_date_str = f"{m}/{d}"
            post_time_str = "18:00" if "事前告知" in str(event_type) else str(event_time)
    except Exception:
        post_date_str = event_date
        post_time_str = "18:00" if "事前告知" in str(event_type) else event_time
    return (post_date_str, post_time_str)


# クエリパラメータでOAuthコールバック（code）を処理
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
    expected_state = st.session_state.get("oauth_state")
    if expected_state and state and state != expected_state:
        st.session_state["oauth_error"] = "OAuthの検証に失敗しました。もう一度「Googleカレンダーと連携する」を押してください。"
        return
    try:
        creds = exchange_code_for_credentials(redirect_uri, code, state=expected_state or state)
    except Exception as e:
        st.session_state["oauth_error"] = str(e)
        return
    if creds:
        st.session_state["google_credentials"] = credentials_to_dict(creds)
        st.session_state["oauth_just_completed"] = True
        if "oauth_state" in st.session_state:
            del st.session_state["oauth_state"]
        if "oauth_error" in st.session_state:
            del st.session_state["oauth_error"]
        # rerunしない＝このまま描画を続けて「連携済み」を表示（Streamlit Cloudでrerunするとセッションが消えて空白になるため）
    else:
        st.session_state["oauth_error"] = "トークンの取得に失敗しました。もう一度「Googleカレンダーと連携する」からやり直してください。"

if GOOGLE_API_AVAILABLE:
    _handle_oauth_callback()

# タブ：Google連携 / 貼り付け / 手動入力
tab_names = ["🔗 Googleカレンダーと連携", "📋 貼り付けで入力", "✏️ 手動入力"]
if not GOOGLE_API_AVAILABLE:
    tab_names = ["📋 貼り付けで入力", "✏️ 手動入力"]

tabs = st.tabs(tab_names)
tab_idx = 0

# --- Googleカレンダーと連携タブ ---
if GOOGLE_API_AVAILABLE:
    with tabs[tab_idx]:
        redirect_uri = os.environ.get("REDIRECT_URI") or (
            st.secrets.get("REDIRECT_URI") if hasattr(st, "secrets") else None
        ) or "http://localhost:8501"
        auth_payload = get_authorization_url(redirect_uri)
        auth_url = None
        if auth_payload:
            auth_url, oauth_state = auth_payload
            st.session_state["oauth_state"] = oauth_state

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
                    except Exception:
                        st.session_state["calendar_list"] = [{"id": "primary", "summary": "メイン"}]

            cal_list = st.session_state.get("calendar_list", [{"id": "primary", "summary": "メイン"}])
            cal_options = [f"{c.get('summary', '')} ({c.get('id', '')})" for c in cal_list]
            cal_ids = [c.get("id", "primary") for c in cal_list]
            cal_idx = st.selectbox("取得するカレンダーを選択", range(len(cal_list)), format_func=lambda i: cal_options[i])
            selected_calendar_id = cal_ids[cal_idx] if cal_ids else "primary"

            if st.button("📅 予定を取得（1ヶ月分）"):
                with st.spinner("1ヶ月分の予定を取得しています..."):
                    try:
                        creds, updated = refresh_credentials_if_needed(creds)
                        if updated is not None:
                            st.session_state["google_credentials"] = updated
                        events = fetch_upcoming_events(
                            creds,
                            calendar_id=selected_calendar_id,
                            max_results=250,
                            days_ahead=31,
                        )
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

                st.divider()
                st.markdown("**1ヶ月分を一括生成してスプレッドシート用に出力**")
                if st.button("📋 1ヶ月分の告知文を一括生成", type="primary", key="btn_bulk"):
                    generator = AnnouncementGenerator()
                    rows = []
                    for ed in events_list:
                        ev_copy = ed.copy()
                        for k in ("_id", "_raw_summary", "_raw_description"):
                            ev_copy.pop(k, None)
                        event_type = ev_copy.get("event_type", "")
                        post_date, post_time = _get_post_date_time(
                            event_type, ev_copy.get("date", ""), ev_copy.get("time", "")
                        )
                        channel_name = _get_channel_name(event_type)
                        is_valid = generator.validate_event_data(ev_copy)[0]
                        if not is_valid:
                            continue
                        ann = generator.generate(ev_copy) or ""
                        msg = (ann or "").replace("\r", "\n")
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
                        st.caption("💡 事前告知＝前日18:00・まもなく開始＝開始5分前。A列=メッセージ, B列=日付(投稿日), C列=時間(投稿時間), D列=チャンネル名。")
                    else:
                        st.warning("生成できる予定がありませんでした。")
    tab_idx += 1

# --- 貼り付けで入力タブ ---
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

# --- 手動入力タブ ---
with tabs[tab_idx]:
    st.markdown("**イベント情報を手動で入力**")
    col1, col2 = st.columns(2)
    
    with col1:
        manual_event_type = st.selectbox(
            "イベント種別",
            [
                "ジャンル特化グルコン（事前告知）",
                "ジャンル特化グルコン（間もなく開始）",
                "万垢生限定オン会（事前告知）",
                "万垢生限定オン会（間もなく開始）",
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

# 生成ボタン（貼り付け・手動入力タブ用）
if st.button("📝 告知文を生成", type="primary", key="btn_generate"):
    event_data = None
    
    if calendar_text.strip():
        # カレンダーからパース
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
        # 手動入力から作成
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
        
        # 必須項目チェック
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
- ジャンル特化グルコン（事前告知 / 間もなく開始）、万垢生限定オン会（事前告知 / 間もなく開始）
- 生徒対談（事前告知 / 間もなく開始）
- 講師対談（事前告知 / 間もなく開始）
- オン会（事前告知 / 間もなく開始）
""")
