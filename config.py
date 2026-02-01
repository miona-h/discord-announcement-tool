"""
設定ファイル
共通プロンプトやデフォルト設定を管理
"""

# テンプレートファイルのパス
TEMPLATES_CSV_PATH = "templates/templates.csv"

# 出力ディレクトリ
OUTPUT_DIR = "output"

# 日付フォーマット
DATE_FORMAT = "%Y年%m月%d日"
TIME_FORMAT = "%H:%M"

# イベント種別ごとの固定Zoom情報
FIXED_ZOOM_INFO = {
    "ジャンル特化グルコン（事前告知）": {
        "zoom_url": "https://us06web.zoom.us/j/86783391679?pwd=A7t1L99e5NHZBJOj5tMEPNHOUAyhh8.1",
        "meeting_id": "867 8339 1679",
        "passcode": "0000"
    },
    "ジャンル特化グルコン（間もなく開始）": {
        "zoom_url": "https://us06web.zoom.us/j/86783391679?pwd=A7t1L99e5NHZBJOj5tMEPNHOUAyhh8.1",
        "meeting_id": "867 8339 1679",
        "passcode": "0000"
    },
    "ジャンル特化グルコン（卒業生向け）": {
        "zoom_url": "https://us06web.zoom.us/j/86783391679?pwd=A7t1L99e5NHZBJOj5tMEPNHOUAyhh8.1",
        "meeting_id": "867 8339 1679",
        "passcode": "0000"
    },
    "生徒対談（事前告知）": {
        "zoom_url": "https://us06web.zoom.us/j/84044741268?pwd=kkc7BHgUm82aaiNC3HxHGZVMSVF799.1",
        "meeting_id": "840 4474 1268",
        "passcode": "009706"
    },
    "生徒対談（間もなく開始）": {
        "zoom_url": "https://us06web.zoom.us/j/84044741268?pwd=kkc7BHgUm82aaiNC3HxHGZVMSVF799.1",
        "meeting_id": "840 4474 1268",
        "passcode": "009706"
    },
    "講師対談（事前告知）": {
        "zoom_url": "https://us06web.zoom.us/j/84044741268?pwd=kkc7BHgUm82aaiNC3HxHGZVMSVF799.1",
        "meeting_id": "840 4474 1268",
        "passcode": "009706"
    },
    "講師対談（間もなく開始）": {
        "zoom_url": "https://us06web.zoom.us/j/84044741268?pwd=kkc7BHgUm82aaiNC3HxHGZVMSVF799.1",
        "meeting_id": "840 4474 1268",
        "passcode": "009706"
    },
    "オン会（事前告知）": {
        "zoom_url": "https://us06web.zoom.us/j/81644840347?pwd=NdMeW9PWVXz4Wp2QqscIHvjecEUV6L.1",
        "meeting_id": "816 4484 0347",
        "passcode": "121550"
    },
    "オン会（間もなく開始）": {
        "zoom_url": "https://us06web.zoom.us/j/81644840347?pwd=NdMeW9PWVXz4Wp2QqscIHvjecEUV6L.1",
        "meeting_id": "816 4484 0347",
        "passcode": "121550"
    },
}

# ジャンルと絵文字のマッピング
GENRE_EMOJI_MAP = {
    "レシピ": "🍳",
    "子育て": "👶",
    "お金": "💰",
    "スキル": "💰",
    "お金・スキル": "💰",
    "美容": "💄",
    "ファッション": "👗",
    "健康": "💪",
    "ダイエット": "🏃‍♀️",
    "スポット": "📍",
    "暮らし": "🏠",
    "ビジネス": "💼",
    "教育": "📚",
    "エンタメ": "🎬",
    "スポーツ": "⚽",
    "音楽": "🎵",
    "アート": "🎨",
    "テクノロジー": "💻",
    "投資": "📈",
    "不動産": "🏘️",
    "婚活": "💑",
    "ママ": "👩‍👧",
    "パパ": "👨‍👦",
}

def add_genre_emoji(genre: str) -> str:
    if not genre:
        return genre
    if any(ord(char) > 0x1F000 for char in genre):
        return genre
    genre_lower = genre.lower()
    for keyword, emoji in GENRE_EMOJI_MAP.items():
        if keyword in genre or keyword.lower() in genre_lower:
            genre_clean = genre.replace("ジャンル", "").strip()
            if emoji:
                return f"{emoji}{genre_clean}ジャンル"
            else:
                return f"{genre_clean}ジャンル"
    return genre

SUPPORTED_VARIABLES = [
    "date", "time", "time_jp", "event_type", "teacher_name",
    "instagram_url", "zoom_url", "event_name", "genre",
    "meeting_id", "passcode", "facilitator", "discussion_end_time",
    "end_time", "representative_name",
]
