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

from parse_calendar import parse_calendar_text
from generate_announcement import AnnouncementGenerator


st.set_page_config(
    page_title="Discord告知文生成ツール",
    page_icon="📢",
    layout="centered",
)

st.title("📢 Discord告知文 自動生成ツール")
st.caption("SnsClubオンラインイベント用の告知文章を生成します")

# タブで入力方法を切り替え
tab1, tab2 = st.tabs(["📅 Googleカレンダーから入力", "✏️ 手動入力"])

with tab1:
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

with tab2:
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

# 生成ボタン
if st.button("📝 告知文を生成", type="primary"):
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
- ジャンル特化グルコン（事前告知 / 間もなく開始 / 卒業生向け）
- 生徒対談（事前告知 / 間もなく開始）
- 講師対談（事前告知 / 間もなく開始）
- オン会（事前告知 / 間もなく開始）
""")
