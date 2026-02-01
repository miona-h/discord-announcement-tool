#!/usr/bin/env python3
"""
Googleカレンダーの情報をパースしてJSON形式に変換するスクリプト

使い方:
    python parse_calendar.py "【ジャンル特化グルコン】よだれ夫婦講師（レシピジャンル）" "1月31日" "午後12:00" "https://www.instagram.com/yodare_recipe/"
    
または、テキストファイルから読み込み:
    python parse_calendar.py --file calendar_event.txt
"""

import re
import json
import sys
import argparse
from datetime import datetime
from typing import Dict, Optional


def parse_event_name(event_name: str) -> Dict[str, str]:
    """
    イベント名から情報を抽出
    
    例: 【ジャンル特化グルコン】よだれ夫婦講師（レシピジャンル）
    """
    result = {}
    
    # イベント種別を判定（万垢生限定オン会は「万垢」または絵文字付きで判定）
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
        result["event_type"] = "ジャンル特化グルコン（事前告知）"  # デフォルト
    
    # 講師名を抽出（【】と（）の間）
    match = re.search(r'【.*?】(.+?)講師', event_name)
    if match:
        result["teacher_name"] = match.group(1).strip()
    else:
        # パターン2: 【】の後、講師の前
        match = re.search(r'】(.+?)講師', event_name)
        if match:
            result["teacher_name"] = match.group(1).strip()
    
    # ジャンルを抽出（（）内）
    match = re.search(r'（(.+?)）', event_name)
    if match:
        genre = match.group(1).strip()
        # configから絵文字追加関数をインポート
        try:
            import config
            result["genre"] = config.add_genre_emoji(genre)
        except ImportError:
            # configがインポートできない場合はデフォルト処理
            if "レシピ" in genre:
                result["genre"] = f"🍳{genre}"
            elif "子育て" in genre:
                result["genre"] = f"👶{genre}"
            elif "お金" in genre or "スキル" in genre:
                result["genre"] = f"💰{genre}"
            else:
                result["genre"] = genre
    else:
        result["genre"] = ""
    
    return result


def parse_date(date_str: str) -> str:
    """
    日付文字列をパースして標準形式に変換
    
    例: "1月31日" -> "1/31"
         "1月 31日 (土曜日)" -> "1/31"
    """
    # 月と日を抽出
    match = re.search(r'(\d+)月\s*(\d+)日', date_str)
    if match:
        month = match.group(1)
        day = match.group(2)
        return f"{month}/{day}"
    
    # 既に "1/31" 形式の場合
    if "/" in date_str:
        return date_str
    
    return date_str


def parse_time(time_str: str) -> str:
    """
    時間文字列をパースして24時間形式に変換
    
    例: "午後12:00" -> "12:00"
         "午前9:00" -> "9:00"
         "21:00" -> "21:00"
    """
    # 既に "12:00" 形式の場合
    if re.match(r'^\d{1,2}:\d{2}', time_str):
        return time_str.split("～")[0].strip()  # "12:00～1:00" の場合、最初の時間を取得
    
    # "午後12:00" 形式の場合
    match = re.search(r'(午前|午後)?\s*(\d{1,2}):(\d{2})', time_str)
    if match:
        am_pm = match.group(1)
        hour = int(match.group(2))
        minute = match.group(3)
        
        if am_pm == "午後" and hour != 12:
            hour += 12
        elif am_pm == "午前" and hour == 12:
            hour = 0
        
        return f"{hour:02d}:{minute}"
    
    return time_str.split("～")[0].strip()


def parse_calendar_text(text: str) -> Dict:
    """
    Googleカレンダーのテキスト情報をパースしてJSON形式に変換
    """
    lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
    
    result = {}
    
    # イベント名を探す（【】を含む行）
    event_name = None
    for line in lines:
        if "【" in line and "】" in line:
            event_name = line
            break
    
    if event_name:
        parsed = parse_event_name(event_name)
        result.update(parsed)
    
    # 日付を探す（"月"と"日"を含む行）
    for line in lines:
        if "月" in line and "日" in line:
            result["date"] = parse_date(line)
            break
    
    # 時間を探す（"午前"、"午後"、または":"を含む行）
    for line in lines:
        if "午前" in line or "午後" in line or (":" in line and "時" not in line):
            result["time"] = parse_time(line)
            break
    
    # Instagramリンクを探す
    for line in lines:
        if "instagram.com" in line.lower():
            # "Instagramリンク："の後のURLを抽出
            match = re.search(r'https://www\.instagram\.com/[^\s]+', line)
            if match:
                result["instagram_url"] = match.group(0)
            else:
                # 行全体がURLの場合
                if line.startswith("http"):
                    result["instagram_url"] = line
            break
    
    # Zoom情報は固定情報として自動挿入されるので、ここでは取得しない
    
    return result


def main():
    parser = argparse.ArgumentParser(
        description='Googleカレンダーの情報をパースしてJSON形式に変換'
    )
    parser.add_argument(
        '--file', '-f',
        help='カレンダー情報が記載されたテキストファイル'
    )
    parser.add_argument(
        '--output', '-o',
        help='出力JSONファイルのパス（指定しない場合は標準出力）'
    )
    parser.add_argument(
        'text',
        nargs='*',
        help='カレンダー情報（複数行のテキスト）'
    )
    
    args = parser.parse_args()
    
    # テキストを読み込む
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                text = f.read()
        except FileNotFoundError:
            print(f"エラー: ファイルが見つかりません: {args.file}")
            sys.exit(1)
    elif args.text:
        text = '\n'.join(args.text)
    else:
        # 標準入力から読み込み
        text = sys.stdin.read()
    
    if not text.strip():
        print("エラー: 入力テキストが空です")
        sys.exit(1)
    
    # パース
    result = parse_calendar_text(text)
    
    # 必須項目のチェック
    required = ['date', 'time', 'event_type']
    missing = [field for field in required if field not in result]
    
    if missing:
        print(f"警告: 以下の情報が不足しています: {', '.join(missing)}")
        print("\nパース結果:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("\n不足している情報を手動で追加してください。")
    else:
        # JSONを出力
        json_output = json.dumps(result, ensure_ascii=False, indent=2)
        
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(json_output)
            print(f"✓ JSONファイルを保存しました: {args.output}")
        else:
            print(json_output)


if __name__ == '__main__':
    main()
