#!/usr/bin/env python3
"""Discordオンラインイベント配信文章 自動生成ツール（MVP）"""

import json
import csv
import sys
import os
import argparse
from pathlib import Path
from typing import Dict, Optional
import config


class AnnouncementGenerator:
    """告知文章生成クラス"""
    
    def __init__(self, templates_path: str = None):
        self.templates_path = templates_path or config.TEMPLATES_CSV_PATH
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, str]:
        templates = {}
        if not os.path.exists(self.templates_path):
            return templates
        try:
            with open(self.templates_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    event_type = row.get('event_type', '').strip()
                    template = row.get('template', '').strip()
                    if event_type and template:
                        templates[event_type] = template
        except Exception as e:
            print(f"エラー: テンプレートファイルの読み込みに失敗しました: {e}")
            sys.exit(1)
        return templates
    
    def _replace_variables(self, template: str, event_data: Dict) -> str:
        result = template
        event_type = event_data.get('event_type', '').strip()
        if event_type in config.FIXED_ZOOM_INFO:
            fixed_info = config.FIXED_ZOOM_INFO[event_type]
            for key, value in fixed_info.items():
                if key not in event_data or not event_data.get(key):
                    event_data[key] = value
        if 'time' in event_data and 'time_jp' not in event_data:
            time_str = str(event_data['time']).strip()
            if ':' in time_str:
                hour = time_str.split(':')[0]
                event_data['time_jp'] = f"{hour}時"
            else:
                event_data['time_jp'] = time_str
        if 'genre' in event_data and event_data.get('genre'):
            event_data['genre'] = config.add_genre_emoji(str(event_data['genre']))
        for var in config.SUPPORTED_VARIABLES:
            placeholder = f"{{{{{var}}}}}"
            value = event_data.get(var, "")
            result = result.replace(placeholder, str(value))
        return result
    
    def generate(self, event_data: Dict) -> Optional[str]:
        event_type = event_data.get('event_type', '').strip()
        if not event_type or event_type not in self.templates:
            return None
        return self._replace_variables(self.templates[event_type], event_data)
    
    def validate_event_data(self, event_data: Dict) -> tuple[bool, list[str]]:
        errors = []
        event_type = event_data.get('event_type', '').strip()
        has_fixed_zoom = event_type in config.FIXED_ZOOM_INFO
        basic_required = ['time', 'event_type'] if has_fixed_zoom else ['time', 'event_type', 'zoom_url']
        event_specific_required = {
            'ジャンル特化グルコン（間もなく開始）': ['genre', 'teacher_name', 'instagram_url'],
            '生徒対談（間もなく開始）': [], '講師対談（間もなく開始）': [],
            'オン会（間もなく開始）': [], 'オン会（事前告知）': [],
        }
        no_teacher_events = ['オン会（事前告知）', 'オン会（間もなく開始）']
        if '（事前告知）' in event_type or '（卒業生向け）' in event_type:
            if has_fixed_zoom:
                required_fields = basic_required + (['date'] if event_type in no_teacher_events else ['date', 'teacher_name'])
            else:
                required_fields = basic_required + (['date', 'meeting_id', 'passcode'] if event_type in no_teacher_events else ['date', 'teacher_name', 'meeting_id', 'passcode'])
        elif event_type in event_specific_required:
            required_fields = basic_required + event_specific_required[event_type]
        else:
            required_fields = basic_required + (['date'] if event_type in no_teacher_events else ['date', 'teacher_name'])
        for field in required_fields:
            if field not in event_data or not str(event_data[field]).strip():
                errors.append(f"必須項目 '{field}' が不足しています")
        return len(errors) == 0, errors
