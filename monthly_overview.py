#!/usr/bin/env python3
"""月全体のイベント案内文を生成するモジュール"""

import re
from datetime import datetime
from typing import Dict, List, Any

try:
    import config
    MONTHLY_GENRE_DISCORD_EMOJI = getattr(config, "MONTHLY_GENRE_DISCORD_EMOJI", {})
except ImportError:
    MONTHLY_GENRE_DISCORD_EMOJI = {}

WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _parse_date_for_sort(date_str: str, time_str: str, year: int) -> datetime:
    """date "2/24", time "21:00" を datetime に変換（ソート用）"""
    if not date_str or not time_str:
        return datetime.max
    try:
        parts = str(date_str).strip().split("/")
        if len(parts) < 2:
            return datetime.max
        m, d = int(parts[0]), int(parts[1])
        t = str(time_str).strip()
        hour, minute = 0, 0
        if ":" in t:
            hp = t.split(":")
            hour = int(hp[0]) if hp else 0
            minute = int(hp[1]) if len(hp) > 1 else 0
        return datetime(year, m, d, hour, minute)
    except (ValueError, IndexError):
        return datetime.max


def _format_date_long(date_str: str, time_str: str, year: int) -> str:
    """2月24日（火）　21:00〜 形式"""
    try:
        parts = str(date_str).strip().split("/")
        if len(parts) < 2:
            return f"{date_str} {time_str}〜"
        m, d = int(parts[0]), int(parts[1])
        dt = datetime(year, m, d)
        w = WEEKDAY_JA[dt.weekday()]
        return f"{m}月{d}日（{w}）　{time_str}〜"
    except (ValueError, IndexError):
        return f"{date_str} {time_str}〜"


def _format_date_short(date_str: str, time_str: str, year: int) -> str:
    """2/24（火）21:00～ 形式"""
    try:
        parts = str(date_str).strip().split("/")
        if len(parts) < 2:
            return f"{date_str} {time_str}～"
        m, d = int(parts[0]), int(parts[1])
        dt = datetime(year, m, d)
        w = WEEKDAY_JA[dt.weekday()]
        return f"{m}/{d}（{w}）{time_str}～"
    except (ValueError, IndexError):
        return f"{date_str} {time_str}～"


def _genre_discord_emoji(genre: str) -> str:
    """ジャンル文字列からDiscord絵文字コードを返す（例: スポット → :round_pushpin:）"""
    if not genre:
        return ""
    genre_clean = re.sub(r"^[\s\U0001F300-\U0001F9FF]+", "", str(genre)).replace("ジャンル", "").strip()
    for keyword, emoji in MONTHLY_GENRE_DISCORD_EMOJI.items():
        if keyword in genre or keyword in genre_clean:
            return emoji
    return ""


def _genre_display_name(genre: str) -> str:
    """表示用ジャンル名（例: スポットジャンル）"""
    if not genre:
        return ""
    g = re.sub(r"^[\s\U0001F300-\U0001F9FF]+", "", str(genre)).strip()
    return f"{g}ジャンル" if "ジャンル" not in g else g


def _num(i: int) -> str:
    """①②③形式の番号（1〜10は丸数字、それ以上は数字）"""
    return "①②③④⑤⑥⑦⑧⑨⑩"[i - 1] if 1 <= i <= 10 else str(i)


def build_monthly_overview(events: List[Dict[str, Any]], month_str: str) -> str:
    """
    イベント一覧から月全体の案内文を生成する。
    順序: 特別講義（あれば）→ 講師対談 → 生徒対談 → ジャンル特化グルコン（ジャンルごと・日付順）
    """
    year = datetime.now().year
    # 内部用キーを除いたコピーで、1イベント1件（事前告知のみ）
    clean = []
    for ed in events:
        ev = {k: v for k, v in ed.items() if not k.startswith("_")}
        et = ev.get("event_type", "")
        if "（事前告知）" not in et:
            continue
        clean.append(ev)

    special = []       # 特別講義
    instructor = []    # 講師対談
    student = []      # 生徒対談
    genre_events = []  # ジャンル特化グルコン

    for ev in clean:
        et = ev.get("event_type", "")
        if "特別講義" in et:
            special.append(ev)
        elif "講師対談" in et:
            instructor.append(ev)
        elif "生徒対談" in et:
            student.append(ev)
        elif "ジャンル特化グルコン" in et:
            genre_events.append(ev)

    def sort_by_date(lst):
        return sorted(lst, key=lambda e: _parse_date_for_sort(e.get("date", ""), e.get("time", ""), year))

    instructor = sort_by_date(instructor)
    student = sort_by_date(student)
    genre_events = sort_by_date(genre_events)

    lines = [f"# {month_str}のイベント案内📢", ""]

    # 特別講義（あれば）
    if special:
        special = sort_by_date(special)
        lines.append("## 【特別講義】")
        lines.append("")
        for i, ev in enumerate(special, 1):
            date_fmt = _format_date_long(ev.get("date", ""), ev.get("time", ""), year)
            lines.append(f"{_num(i)}開催日：{date_fmt}")
            lines.append(f"講師：{ev.get('teacher_name', '')}")
            if ev.get("instagram_url"):
                lines.append(ev["instagram_url"].rstrip("/"))
            lines.append("")
        lines.append("")

    # 講師対談
    lines.append("## 【講師対談】")
    lines.append("")
    if instructor:
        for ev in instructor:
            date_fmt = _format_date_long(ev.get("date", ""), ev.get("time", ""), year)
            lines.append(f"開催日：{date_fmt}")
            lines.append(f"講師：{ev.get('teacher_name', '')}")
            if ev.get("instagram_url"):
                lines.append(ev["instagram_url"].rstrip("/"))
            lines.append("")
    else:
        lines.append("（今月の予定はありません）")
        lines.append("")
    lines.append("")

    # 生徒対談
    lines.append("## 【生徒対談】")
    lines.append("")
    if student:
        for i, ev in enumerate(student, 1):
            date_fmt = _format_date_long(ev.get("date", ""), ev.get("time", ""), year)
            lines.append(f"{_num(i)}開催日：{date_fmt}")
            lines.append(str(ev.get("teacher_name", "")))
            if ev.get("instagram_url"):
                lines.append(ev["instagram_url"].rstrip("/"))
            lines.append("")
    else:
        lines.append("（今月の予定はありません）")
        lines.append("")
    lines.append("")

    # ジャンル特化グルコン（ジャンルごとにまとめ、日付順）
    lines.append("## 【ジャンル特化グルコン】")
    lines.append("")

    if genre_events:
        by_genre: Dict[str, List[Dict]] = {}
        genre_order: List[str] = []  # 最初に出た順を保持
        for ev in genre_events:
            g = ev.get("genre", "") or "その他"
            g_key = re.sub(r"^[\s\U0001F300-\U0001F9FF]+", "", str(g)).strip()
            if not g_key:
                g_key = "その他"
            if g_key not in by_genre:
                by_genre[g_key] = []
                genre_order.append(g_key)
            by_genre[g_key].append(ev)

        for g_key in genre_order:
            group = sort_by_date(by_genre[g_key])
            emoji = _genre_discord_emoji(group[0].get("genre", "") or g_key)
            label = _genre_display_name(group[0].get("genre", "") or g_key)
            lines.append(f"## {emoji}{label}")
            lines.append("")
            for i, ev in enumerate(group, 1):
                date_fmt = _format_date_short(ev.get("date", ""), ev.get("time", ""), year)
                lines.append(f"{_num(i)}開催日：{date_fmt}")
                lines.append(f"講師：{ev.get('teacher_name', '')}")
                if ev.get("instagram_url"):
                    lines.append(ev["instagram_url"].rstrip("/"))
                lines.append("")
            lines.append("")
    else:
        lines.append("（今月の予定はありません）")
        lines.append("")

    return "\n".join(lines).strip()
