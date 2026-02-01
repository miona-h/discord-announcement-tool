#!/usr/bin/env python3
"""Googleカレンダーの情報をパースしてJSON形式に変換するスクリプト"""

import re
import json
import sys
import argparse
from typing import Dict


def parse_event_name(event_name: str) -> Dict[str, str]:
    result = {}
    if "万垢生限定オン会" in event_name or ("万垢" in event_name and "限定オン会" in event_name):
        result["event_type"] = "万垢生限定オン会（事前告知）"
    elif "ジャンル特化グルコン" in event_name:
        result["event_type"] = "ジャンル特化グルコン（事前告知）"
    elif "生徒対談" in event_name:
        result["event_type"] = "生徒対談（事前告知）"
    elif "講師対談" in event_name:
        result["event_type"] = "講師対談（事前告知）"
    elif "オン会" in event_name:
        result["event_type"] = "オン会（事前告知）"
    else:
        result["event_type"] = "ジャンル特化グルコン（事前告知）"

    # ジャンル: （〇〇）から抽出（例: （スポット）→ スポット）
    match_genre = re.search(r'（(.+?)）', event_name)
    if match_genre:
        genre = match_genre.group(1).strip()
        try:
            import config
            result["genre"] = config.add_genre_emoji(genre)
        except ImportError:
            result["genre"] = genre
    else:
        result["genre"] = ""

    # 講師名・ゲスト名: 新カレンダー名形式に合わせて抽出
    if "ジャンル特化グルコン" in event_name:
        # 【ジャンル特化グルコン】 カナノ⌇埼玉グルメ＆カフェ（スポット）
        m = re.search(r'【ジャンル特化グルコン】\s*(.+?)（.+?）', event_name)
        if m:
            result["teacher_name"] = m.group(1).strip()
        else:
            m = re.search(r'【ジャンル特化グルコン】\s*(.+)', event_name)
            if m:
                result["teacher_name"] = m.group(1).strip()
    elif "講師対談" in event_name:
        # 【講師対談】はるパパ⌇親子で楽しむ0歳カラダあそび
        m = re.search(r'【講師対談】\s*(.+)', event_name)
        if m:
            result["teacher_name"] = m.group(1).strip()
    elif "生徒対談" in event_name:
        # 【生徒対談】ぽぽ⌇看護師・発酵料理士アドバイザー
        m = re.search(r'【生徒対談】\s*(.+)', event_name)
        if m:
            result["teacher_name"] = m.group(1).strip()

    return result


def parse_date(date_str: str) -> str:
    match = re.search(r'(\d+)月\s*(\d+)日', date_str)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    return date_str if "/" in date_str else date_str


def parse_time(time_str: str) -> str:
    if re.match(r'^\d{1,2}:\d{2}', time_str):
        return time_str.split("～")[0].strip()
    match = re.search(r'(午前|午後)?\s*(\d{1,2}):(\d{2})', time_str)
    if match:
        hour = int(match.group(2))
        minute = match.group(3)
        if match.group(1) == "午後" and hour != 12:
            hour += 12
        elif match.group(1) == "午前" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"
    return time_str.split("～")[0].strip()


def parse_calendar_text(text: str) -> Dict:
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    result = {}
    for line in lines:
        if "【" in line and "】" in line:
            result.update(parse_event_name(line))
            break
    for line in lines:
        if "月" in line and "日" in line:
            result["date"] = parse_date(line)
            break
    for line in lines:
        if "午前" in line or "午後" in line or (":" in line and "時" not in line):
            result["time"] = parse_time(line)
            break
    for line in lines:
        if "instagram.com" in line.lower():
            # Zoomリンクの手前で区切り、InstagramのURLのみ抽出
            head = line.split("Zoomリンク")[0].split("Zoom ")[0].strip()
            match = re.search(r'https://www\.instagram\.com/[^\s<>"/]+', head)
            if match:
                result["instagram_url"] = match.group(0).rstrip("/").rstrip(")")
            break
    return result
