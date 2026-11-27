#!/usr/bin/env python3
"""Googleカレンダーの予定から月間カレンダー画像を生成する。"""

from __future__ import annotations

import calendar
import html
import io
import json
import os
import re
import urllib.parse
import urllib.request
from collections import deque
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

try:
    from janome.tokenizer import Tokenizer as JanomeTokenizer
    _JANOME_TOKENIZER = JanomeTokenizer()
except ImportError:
    _JANOME_TOKENIZER = None

try:
    import jpholiday
except ImportError:  # ローカル確認時など、未導入でも画像生成は継続する
    jpholiday = None


DEFAULT_CATEGORY_STYLES = {
    "成果報告": "#FFD6D8",
    "週報提出": "#D9F7D7",
    "オフ会": "#FFF1A8",
    "オン会": "#FFF7C7",
    "対談": "#DDEBFF",
    "グルコン": "#FFF0D5",
    "その他": "#F1F5F9",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _first_existing_path(*relative_paths: str) -> str:
    """GitHub直下配置とサブフォルダ配置の両方に対応する。"""
    candidates = [os.path.join(BASE_DIR, path) for path in relative_paths]
    return next((path for path in candidates if os.path.exists(path)), candidates[0])


SNSCLUB_LOGO_ASSET = _first_existing_path(
    os.path.join("calendar_assets", "snsclub_logo.jpg"), "snsclub_logo.jpg"
)
HEADER_CHARACTER_ASSET = _first_existing_path(
    os.path.join("calendar_assets", "header_character_wave.png"), "header_character_wave.png"
)
NOTO_SANS_JP_FONT = _first_existing_path(
    os.path.join("fonts", "NotoSansJP-Variable.ttf"), "NotoSansJP-Variable.ttf"
)
ROUNDED_TITLE_FONT = _first_existing_path(
    os.path.join("fonts", "Baloo2-Variable.ttf"), "Baloo2-Variable.ttf"
)


def classify_event(event: Dict[str, Any]) -> str:
    """予定名を優先して表示カテゴリを判定する。"""
    text = " ".join(
        str(event.get(key, "") or "")
        for key in ("_raw_summary", "event_name", "event_type")
    )
    if "成果報告" in text:
        return "成果報告"
    if "週報" in text:
        return "週報提出"
    if "オフ会" in text:
        return "オフ会"
    if "オン会" in text:
        return "オン会"
    if "対談" in text:
        return "対談"
    if "グルコン" in text:
        return "グルコン"
    return "その他"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc" if bold else "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _rounded_font(size: int) -> ImageFont.FreeTypeFont:
    if os.path.exists(NOTO_SANS_JP_FONT):
        font = ImageFont.truetype(NOTO_SANS_JP_FONT, size=size)
        try:
            font.set_variation_by_axes([800])
        except (AttributeError, OSError):
            pass
        return font
    candidates = [
        "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
        "/System/Library/Fonts/ヒラギノ丸ゴ Pro W4.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return _font(size, True)


def _event_font(size: int) -> ImageFont.FreeTypeFont:
    """予定名用の Noto Sans JP Black（900）を返す。"""
    if os.path.exists(NOTO_SANS_JP_FONT):
        font = ImageFont.truetype(NOTO_SANS_JP_FONT, size=size)
        try:
            font.set_variation_by_name("Black")
        except (AttributeError, OSError):
            try:
                font.set_variation_by_axes([900])
            except (AttributeError, OSError):
                pass
        return font
    return _font(size, True)


def _draw_beginner_mark(draw: ImageDraw.ImageDraw, left: float, top: float, size: int) -> None:
    """フォント未収録でも初心者マークをカラーで表示する。"""
    width = max(8, int(size * 0.9))
    height = max(9, int(size * 1.05))
    x0, y0 = int(left), int(top)
    points = [
        (x0, y0),
        (x0 + width // 2, y0 + max(2, height // 5)),
        (x0 + width, y0),
        (x0 + width, y0 + int(height * 0.68)),
        (x0 + width // 2, y0 + height),
        (x0, y0 + int(height * 0.68)),
    ]
    draw.polygon(points, fill="#FFFFFF")
    draw.polygon(
        [points[0], points[1], points[4], points[5]],
        fill="#67B82E",
    )
    draw.polygon(
        [points[1], points[2], points[3], points[4]],
        fill="#F5E642",
    )
    draw.line(points + [points[0]], fill="#3F6E31", width=max(1, size // 10), joint="curve")


def _event_line_bottom(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    line_y: float,
    line: str,
    font: ImageFont.FreeTypeFont,
    font_size: int,
) -> int:
    """絵文字の代替描画も含めた1行の下端を返す。"""
    if "🔰" not in line:
        return draw.textbbox((center_x, line_y), line, anchor="ma", font=font)[3]
    plain_text = line.replace("🔰", "").replace("️", "")
    text_bottom = line_y
    if plain_text:
        text_bottom = draw.textbbox((0, line_y), plain_text, anchor="la", font=font)[3]
    return int(max(text_bottom, line_y + font_size + 2))


def _draw_event_line(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    line_y: float,
    line: str,
    font: ImageFont.FreeTypeFont,
    font_size: int,
    fill: str,
) -> None:
    """初心者マークを保ったまま予定の1行を中央揃えで描く。"""
    if "🔰" not in line:
        draw.text((center_x, line_y), line, anchor="ma", font=font, fill=fill)
        return
    plain_text = line.replace("🔰", "").replace("️", "")
    text_bbox = draw.textbbox((0, 0), plain_text, anchor="la", font=font) if plain_text else (0, 0, 0, 0)
    text_width = text_bbox[2] - text_bbox[0]
    mark_width = max(8, int(font_size * 0.9))
    gap = max(1, font_size // 8)
    total_width = mark_width + (gap + text_width if plain_text else 0)
    left = center_x - total_width / 2
    _draw_beginner_mark(draw, left, line_y - 1, font_size)
    if plain_text:
        draw.text(
            (left + mark_width + gap, line_y), plain_text,
            anchor="la", font=font, fill=fill,
        )


def _month_title_font(size: int) -> ImageFont.FreeTypeFont:
    """月名に使う、太く柔らかい丸型の英字フォント。"""
    if os.path.exists(ROUNDED_TITLE_FONT):
        font = ImageFont.truetype(ROUNDED_TITLE_FONT, size=size)
        try:
            font.set_variation_by_axes([800])
        except (AttributeError, OSError):
            pass
        return font
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf",
        "/System/Library/Fonts/SFNSRounded.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return _rounded_font(size)


def _is_japanese_holiday(year: int, month: int, day: int) -> bool:
    if jpholiday is None:
        return False
    try:
        return bool(jpholiday.is_holiday(date(year, month, day)))
    except Exception:
        return False


def _event_day(event: Dict[str, Any]) -> Optional[int]:
    try:
        return int(str(event.get("date", "")).strip().split("/")[-1])
    except (TypeError, ValueError):
        return None


def _display_title(event: Dict[str, Any]) -> str:
    title = str(event.get("_raw_summary", "") or event.get("event_name", "") or event.get("event_type", "")).strip()
    return title or "予定"


def _event_text_lines(event: Dict[str, Any], max_chars: int = 9) -> List[str]:
    """文字数を抑えながら「ジャンル → 講師名・内容」の順で表示文言を作る。"""
    override = event.get("_calendar_display_text")
    if override is not None and str(override).strip():
        # 空行も含め、プレビュー画面で入力した改行をそのまま採用する。
        override_text = str(override)
        if "フォロワー別" in override_text:
            # 旧バージョンで保存済みの「フォロワー別\nグルコン」も表示時に除去する。
            override_text = re.sub(r"フォロワー別\s*グルコン", "", override_text)
            override_lines = [
                line for line in override_text.splitlines()
                if line.strip() not in {"フォロワー別", "グルコン"}
            ]
            while override_lines and not override_lines[0].strip():
                override_lines.pop(0)
        else:
            override_lines = override_text.splitlines()
        return [line.strip() for line in override_lines][:10]
    category = classify_event(event)
    summary = _display_title(event)
    event_type = str(event.get("event_type", "") or "")
    genre = str(event.get("genre", "") or "").strip()
    teacher = str(event.get("teacher_name", "") or "").strip()
    lines: List[str] = []

    if "初心者ツール" in summary and "相談会" in summary:
        lines.extend(["🔰初心者ツール", "相談会"])
    elif category == "グルコン":
        # 「ジャンル特化グルコン」「フォロワー別グルコン」は文字数が多いため
        # 種別名を表示せず、ジャンル・講師名・内容だけを表示する。
        if genre:
            clean_genre = re.sub(r"^[^\wぁ-んァ-ン一-鿿]+", "", genre)
            clean_genre = clean_genre.replace("フォロワー別グルコン", "").replace("フォロワー別", "")
            clean_genre = clean_genre.replace("ジャンル", "").strip()
            if clean_genre:
                lines.append(f"【{clean_genre}】")
        else:
            bracket = re.search(r"[【\[]([^】\]]+)[】\]]", summary)
            if bracket:
                label = bracket.group(1).replace("フォロワー別グルコン", "")
                label = label.replace("フォロワー別", "").replace("グルコン", "").strip("・ ")
                if label and "ジャンル特化" not in label:
                    lines.append(f"【{label}】")
    elif category == "対談":
        talk_text = f"{summary} {event_type}"
        if "生徒対談" in talk_text:
            lines.append("【生徒対談】")
        elif "講師対談" in talk_text:
            lines.append("【講師対談】")
        else:
            # マネタイズ対談など、新しい対談名は予定名を勝手に講師対談へ変換しない。
            lines.extend(_wrap_chars(summary, max_chars, 6))
    elif category in ("成果報告", "週報提出"):
        if "成果報告" in summary and "週報" in summary:
            lines.extend(["成果報告・", "週報提出"])
        else:
            lines.append(category)
    elif category == "オフ会":
        lines.extend(_wrap_chars(summary, max_chars, 6))
    elif category == "オン会":
        if "万垢" in summary:
            lines.extend(_wrap_chars(summary, max_chars, 3))
        else:
            lines.extend(["オン会", "(in Zoom)"] if "zoom" in summary.lower() else ["オン会"])
    else:
        # 「特別講義」の種別名は省き、実際の講義名・講師名を優先する。
        clean_summary = re.sub(r"^[【\[]\s*特別講義\s*[】\]]\s*", "", summary).strip()
        clean_summary = re.sub(r"^特別講義[：:\s・-]*", "", clean_summary).strip()
        lines.extend(_wrap_chars(clean_summary or summary, max_chars, 10))

    if teacher and teacher not in " ".join(lines):
        lines.extend(_wrap_chars(teacher, max_chars, 4))
    return lines[:10]


def event_display_text(event: Dict[str, Any]) -> str:
    """プレビュー編集欄へ表示する初期テキストを返す。"""
    return "\n".join(_event_text_lines(event, max_chars=7))


def _visible_event_layout(day_events: List[Dict[str, Any]], card_top: int, card_bottom_limit: int):
    """1日分の表示予定と縦方向のカード範囲を返す。描画とクリック判定で共用する。"""
    def default_weight(event):
        title = _display_title(event)
        if "初心者ツール" in title and "相談会" in title:
            return 3.0
        return 1.0 if classify_event(event) in ("成果報告", "週報提出") else 6.0

    visible_events = day_events[:3]
    available_height = card_bottom_limit - card_top
    submission_events = [
        event for event in day_events if classify_event(event) in ("成果報告", "週報提出")
    ]
    regular_events = [
        event for event in day_events if classify_event(event) not in ("成果報告", "週報提出")
    ]
    if len(submission_events) >= 2 and regular_events:
        visible_events = submission_events[:2] + regular_events[:1]
        default_weights = [1.0, 1.0, default_weight(regular_events[0])]
    elif len(submission_events) == 1 and regular_events and len(day_events) == 2:
        visible_events = submission_events[:1] + regular_events[:1]
        default_weights = [1.0, default_weight(regular_events[0])]
    else:
        default_weights = [default_weight(event) for event in visible_events]

    if not visible_events:
        return [], []
    weights = []
    for event, default_weight in zip(visible_events, default_weights):
        try:
            weights.append(max(0.5, float(event.get("_calendar_height_weight", default_weight))))
        except (TypeError, ValueError):
            weights.append(default_weight)
    total_gap = 5 * (len(visible_events) - 1)
    usable_height = max(len(visible_events) * 20, available_height - total_gap)
    weight_total = sum(weights) or 1
    card_boxes = []
    cursor = card_top
    allocated = 0
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            event_height = usable_height - allocated
        else:
            event_height = max(20, round(usable_height * weight / weight_total))
            allocated += event_height
        card_boxes.append((cursor, min(card_bottom_limit, cursor + event_height)))
        cursor += event_height + 5
    return visible_events, card_boxes


def calendar_event_hit_at_point(
    events: List[Dict[str, Any]], year: int, month: int, x: float, y: float
) -> Dict[str, str]:
    """クリックされた予定キーと、カード・画像枠のどちらかを返す。"""
    width, height = 1080, 1920
    margin, gap = 14, 6
    header_h, weekday_h = 260, 78
    grid_top = header_h + weekday_h
    cell_w = (width - margin * 2 - gap * 6) // 7
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    cell_h = (height - grid_top - margin - gap * (len(weeks) - 1)) // len(weeks)

    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for event in events:
        day = _event_day(event)
        if day:
            by_day.setdefault(day, []).append(event)
    for day_events in by_day.values():
        day_events.sort(key=lambda event: str(event.get("time", "")))

    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            if not day:
                continue
            x0 = margin + col * (cell_w + gap)
            y0 = grid_top + row * (cell_h + gap)
            if not (x0 <= x <= x0 + cell_w and y0 <= y <= y0 + cell_h):
                continue
            day_events = by_day.get(day, [])
            visible_events, card_boxes = _visible_event_layout(day_events, y0 + 54, y0 + cell_h - 8)
            for event, (card_top, card_bottom) in zip(visible_events, card_boxes):
                if card_top <= y <= card_bottom:
                    event_key = str(event.get("_calendar_image_key", "") or "")
                    compact_card = len(day_events) > 1 and card_bottom - card_top < 180
                    minimum_icon_height = 105 if compact_card else 150
                    if card_bottom - card_top >= minimum_icon_height:
                        icon_size = 38 if compact_card else min(70, card_bottom - card_top - 12)
                        icon_x = x0 + (cell_w - icon_size) // 2
                        icon_y = card_bottom - icon_size - 6
                        if icon_x - 4 <= x <= icon_x + icon_size + 4 and icon_y - 4 <= y <= icon_y + icon_size + 4:
                            return {"event_key": event_key, "region": "image"}
                    return {"event_key": event_key, "region": "card"}
            return {"event_key": "", "region": ""}
    return {"event_key": "", "region": ""}


def calendar_event_key_at_point(
    events: List[Dict[str, Any]], year: int, month: int, x: float, y: float
) -> str:
    """後方互換用：クリックされた予定キーだけを返す。"""
    return calendar_event_hit_at_point(events, year, month, x, y).get("event_key", "")


def _wrap_chars(text: str, max_chars: int, max_lines: int) -> List[str]:
    """最大文字数を基準に、単語を途中で切らずに折り返す。"""
    source = str(text or "").strip()
    if not source:
        return [""]

    # 空白を伴う縦線は「講師名｜説明」の明示的な区切りとして改行を優先する。
    source = re.sub(r"\s+([｜︴|])\s+", r" \1\n", source)
    paragraphs = source.splitlines()
    lines: List[str] = []

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        if _JANOME_TOKENIZER is not None:
            words = [
                token.surface for token in _JANOME_TOKENIZER.tokenize(paragraph)
                if token.surface and not token.surface.isspace()
            ]
        else:
            # Janome未導入時も英数字の単語だけは途中で分割しない。
            words = re.findall(r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*|.", re.sub(r"\s+", "", paragraph))

        # 「学ぶiPhone」のような短い日本語＋英単語は一つの意味単位として扱う。
        merged_words: List[str] = []
        for word in words:
            if (
                re.fullmatch(r"[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*", word)
                and merged_words
                and re.search(r"[ぁ-んァ-ン一-鿿]", merged_words[-1])
                and len(merged_words[-1]) <= 3
            ):
                merged_words[-1] += word
            else:
                merged_words.append(word)

        current = ""
        for word in merged_words:
            if not current:
                current = word
            elif len(current) + len(word) <= max_chars:
                current += word
            else:
                lines.append(current)
                current = word
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) >= max_lines:
            break
    return lines[:max_lines] or [""]


def _remove_edge_background(source: Image.Image) -> Image.Image:
    """四隅と同系色で画像端につながる背景だけを透過する。"""
    image = source.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    if width < 2 or height < 2:
        return image

    corners = [pixels[0, 0], pixels[width - 1, 0], pixels[0, height - 1], pixels[width - 1, height - 1]]
    opaque_corners = [pixel for pixel in corners if pixel[3]]
    if len(opaque_corners) < 2:
        return image
    reference = max(
        opaque_corners,
        key=lambda candidate: sum(
            1 for other in opaque_corners
            if sum(abs(candidate[channel] - other[channel]) for channel in range(3)) <= 75
        ),
    )
    matching_corners = sum(
        1 for other in opaque_corners
        if sum(abs(reference[channel] - other[channel]) for channel in range(3)) <= 75
    )
    if matching_corners < 2:
        return image

    queue = deque()
    for x in range(width):
        queue.extend(((x, 0), (x, height - 1)))
    for y in range(height):
        queue.extend(((0, y), (width - 1, y)))
    visited = set()
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited or not (0 <= x < width and 0 <= y < height):
            continue
        visited.add((x, y))
        r, g, b, a = pixels[x, y]
        if not a or sum(abs((r, g, b)[channel] - reference[channel]) for channel in range(3)) > 90:
            continue
        pixels[x, y] = (r, g, b, 0)
        queue.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    return image


def _read_image(data: Optional[bytes], remove_background: bool = False) -> Optional[Image.Image]:
    if not data:
        return None
    try:
        source = Image.open(io.BytesIO(data)).convert("RGBA")
        return _remove_edge_background(source) if remove_background else source
    except Exception:
        return None


_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def instagram_username(instagram_url: str) -> str:
    """https://www.instagram.com/<name>/ からユーザー名を取り出す。"""
    match = re.search(r"instagram\.com/([A-Za-z0-9._]+)", str(instagram_url or ""), re.I)
    if not match:
        return ""
    name = match.group(1).strip(".").lower()
    return "" if name in {"p", "reel", "reels", "stories", "explore", "accounts"} else name


def _download_image(url: str, timeout: int, headers: Optional[Dict[str, str]] = None) -> Optional[bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(5_000_000)
    if not data:
        return None
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        return None
    return data


def _instagram_via_web_api(username: str, timeout: int) -> Optional[bytes]:
    """Instagram Webが内部で使うプロフィールAPI。サーバーのIPによっては拒否される。"""
    api_url = (
        "https://i.instagram.com/api/v1/users/web_profile_info/?username="
        + urllib.parse.quote(username)
    )
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": _BROWSER_UA,
            "x-ig-app-id": "936619743392459",
            "Accept": "application/json",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            "Referer": f"https://www.instagram.com/{username}/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read(2_000_000).decode("utf-8", "ignore"))
    user = ((payload or {}).get("data") or {}).get("user") or {}
    image_url = user.get("profile_pic_url_hd") or user.get("profile_pic_url")
    return _download_image(image_url, timeout) if image_url else None


def _instagram_via_unavatar(username: str, timeout: int) -> Optional[bytes]:
    """外部サービス unavatar.io 経由（無料枠は1日あたりの回数制限あり）。"""
    return _download_image(
        f"https://unavatar.io/instagram/{urllib.parse.quote(username)}?fallback=false", timeout
    )


def fetch_instagram_profile_image(instagram_url: str, timeout: int = 6) -> Optional[bytes]:
    """Instagramのプロフィール画像を最善努力で取得する。すべて失敗した場合は None。

    1. Instagram Web の内部API
    2. プロフィールページの og:image
    3. unavatar.io
    の順に試す。Instagramはクラウドサーバーからのアクセスを強く制限しているため、
    Streamlit Cloud上ではすべて失敗することがある。
    """
    if not instagram_url or "instagram.com" not in instagram_url.lower():
        return None
    username = instagram_username(instagram_url)
    if username:
        try:
            data = _instagram_via_web_api(username, timeout)
            if data:
                return data
        except Exception:
            pass
    data = _instagram_via_og_image(instagram_url, timeout)
    if data:
        return data
    if username:
        try:
            return _instagram_via_unavatar(username, timeout)
        except Exception:
            return None
    return None


def _instagram_via_og_image(instagram_url: str, timeout: int) -> Optional[bytes]:
    """Instagramページの og:image を取得する。ログイン画面に飛ばされた場合は None。"""
    try:
        page_req = urllib.request.Request(
            instagram_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
            },
        )
        with urllib.request.urlopen(page_req, timeout=timeout) as response:
            page = response.read(2_000_000).decode("utf-8", "ignore")
        match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', page, re.I
        ) or re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page, re.I
        )
        if not match:
            return None
        image_url = html.unescape(match.group(1))
        image_req = urllib.request.Request(image_url, headers={"User-Agent": page_req.headers["User-agent"]})
        with urllib.request.urlopen(image_req, timeout=timeout) as response:
            data = response.read(5_000_000)
        return data if data else None
    except Exception:
        return None


GRADIENT_DIRECTIONS = ("縦", "横", "斜め", "放射")


def _hex_to_rgb(value: str, fallback: str = "#F1F5F9") -> tuple[int, int, int]:
    text = str(value or fallback).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return _hex_to_rgb(fallback) if value != fallback else (241, 245, 249)


def event_background_fill(event: Dict[str, Any], default_color: str) -> Any:
    """予定に保存された背景設定を、単色(str)またはグラデーション(dict)で返す。"""
    color1 = str(event.get("_calendar_background_color") or default_color)
    if str(event.get("_calendar_background_style") or "") != "gradient":
        return color1
    color2 = str(event.get("_calendar_background_color2") or color1)
    direction = str(event.get("_calendar_gradient_direction") or "斜め")
    if direction not in GRADIENT_DIRECTIONS:
        direction = "斜め"
    return {"colors": (color1, color2), "direction": direction}


def _gradient_layer(size: tuple[int, int], colors: tuple[str, str], direction: str) -> Image.Image:
    """2色グラデーション画像を作る。中間に少し明るい光沢を入れて立体感を出す。"""
    width, height = max(1, size[0]), max(1, size[1])
    start = _hex_to_rgb(colors[0])
    end = _hex_to_rgb(colors[1])
    # 256段階の帯を作り、L画像の値(0-255)で位置を指定して色を引く。
    steps = []
    for i in range(256):
        t = i / 255
        rgb = [round(start[c] + (end[c] - start[c]) * t) for c in range(3)]
        # 中央付近にごく薄いハイライト（最大+18%）を重ねて“豪華さ”を出す。
        shine = max(0.0, 1 - abs(t - 0.35) / 0.25) * 0.18
        rgb = [round(v + (255 - v) * shine) for v in rgb]
        steps.append(tuple(rgb))

    vertical = Image.linear_gradient("L")  # 上=0（色1）→下=255（色2）
    horizontal = vertical.rotate(90, expand=True)  # 左=0（色1）→右=255（色2）
    if direction == "横":
        ramp = horizontal
    elif direction == "放射":
        ramp = Image.radial_gradient("L")  # 中心=色1 → 外側=色2
    elif direction == "斜め":
        # 左上=色1 → 右下=色2
        ramp = ImageOps.autocontrast(Image.blend(vertical, horizontal, 0.5))
    else:
        ramp = vertical
    ramp = ramp.resize((width, height), Image.Resampling.BILINEAR)
    palette_rgb = [channel for color in steps for channel in color]
    indexed = ramp.convert("P")
    indexed.putpalette(palette_rgb)
    return indexed.convert("RGBA")


def _fill_rounded(
    image: Image.Image,
    box: tuple[int, int, int, int],
    radius: int,
    fill: Any,
    outline: Optional[str] = None,
    width: int = 0,
) -> None:
    """角丸四角形を単色またはグラデーションで塗る。"""
    draw = ImageDraw.Draw(image)
    if not isinstance(fill, dict):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)
        return
    x0, y0, x1, y1 = [int(v) for v in box]
    size = (max(1, x1 - x0 + 1), max(1, y1 - y0 + 1))
    layer = _gradient_layer(size, tuple(fill.get("colors") or ("#F1F5F9", "#F1F5F9")), str(fill.get("direction") or "斜め"))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    layer.putalpha(mask)
    image.alpha_composite(layer, (x0, y0))
    if outline and width:
        draw.rounded_rectangle(box, radius=radius, outline=outline, width=width)


def _circle_image(source: Image.Image, size: int) -> Image.Image:
    square = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    combined_alpha = ImageChops.multiply(square.getchannel("A"), mask)
    square.putalpha(combined_alpha)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.alpha_composite(square)
    return out


def _paste_snsclub_logo(image: Image.Image) -> None:
    """SnsClubロゴの白余白を除去してヘッダー左上へ置く。"""
    if not os.path.exists(SNSCLUB_LOGO_ASSET):
        return
    try:
        logo = Image.open(SNSCLUB_LOGO_ASSET).convert("RGBA")
    except OSError:
        return
    # ほぼ白い背景を透明化し、ロゴ部分だけに切り詰める。
    gray = ImageOps.grayscale(logo.convert("RGB"))
    mask = gray.point(lambda value: 255 if value < 243 else 0)
    bbox = mask.getbbox()
    if bbox:
        logo = logo.crop(bbox)
        mask = mask.crop(bbox)
        logo.putalpha(mask)
    logo.thumbnail((205, 150), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, (32, 30))


def _paste_header_character(image: Image.Image) -> None:
    """ポーズ違いのキャラクターをヘッダー左側へ配置する。"""
    if not os.path.exists(HEADER_CHARACTER_ASSET):
        return
    try:
        character = Image.open(HEADER_CHARACTER_ASSET).convert("RGBA")
    except OSError:
        return
    character.thumbnail((270, 250), Image.Resampling.LANCZOS)
    image.alpha_composite(character, (105, 7))


def _paste_rotated_pictogram(
    image: Image.Image, kind: str, center: tuple[int, int], angle: float, color: str
) -> None:
    """太めのピクトグラムを個別に傾けて配置する。"""
    size = 86
    layer = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    icon = ImageDraw.Draw(layer)
    if kind == "heart":
        icon.rounded_rectangle((7, 10, 70, 61), radius=16, fill=color)
        icon.polygon([(48, 57), (60, 78), (64, 57)], fill=color)
        # フォント依存のハート記号は環境によって□になるため、図形として描画する。
        icon.ellipse((23, 23, 41, 41), fill="#FFFFFF")
        icon.ellipse((38, 23, 56, 41), fill="#FFFFFF")
        icon.polygon([(23, 33), (56, 33), (39, 53)], fill="#FFFFFF")
    elif kind == "phone":
        icon.rounded_rectangle((22, 7, 65, 77), radius=11, outline=color, width=9)
        icon.rounded_rectangle((34, 14, 53, 20), radius=3, fill=color)
        icon.rounded_rectangle((36, 64, 52, 69), radius=3, fill=color)
    else:
        icon.rounded_rectangle((10, 35, 70, 75), radius=9, fill=color)
        icon.ellipse((17, 8, 43, 34), outline=color, width=8)
        icon.ellipse((45, 8, 71, 34), outline=color, width=8)
        icon.polygon([(70, 44), (84, 35), (84, 75), (70, 66)], fill=color)
    rotated = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    x = int(center[0] - rotated.width / 2)
    y = int(center[1] - rotated.height / 2)
    image.alpha_composite(rotated, (x, y))


def generate_calendar_image(
    events: List[Dict[str, Any]],
    year: int,
    month: int,
    category_colors: Optional[Dict[str, str]] = None,
    category_illustrations: Optional[Dict[str, bytes]] = None,
    instagram_images: Optional[Dict[str, bytes]] = None,
    event_images: Optional[Dict[str, bytes]] = None,
) -> bytes:
    """縦16:9（1080×1920px）のPNGカレンダーを返す。"""
    colors = dict(DEFAULT_CATEGORY_STYLES)
    colors.update(category_colors or {})
    illustrations = category_illustrations or {}
    profile_images = instagram_images or {}
    individual_images = event_images or {}

    width, height = 1080, 1920
    margin, gap = 14, 6
    header_h, weekday_h = 260, 78
    image = Image.new("RGBA", (width, height), "#F4FAFF")
    draw = ImageDraw.Draw(image)

    # 参考画像に合わせた、空・雲・黄色アクセントの明るいヘッダー。
    draw.rectangle((0, 0, width, 270), fill="#EFF5FA")
    draw.ellipse((-95, -130, 250, 180), fill="#ADD0F2")
    draw.ellipse((900, -145, 1180, 170), fill="#F7E16B")
    for cx, cy, rx, ry in ((370, 236, 155, 48), (565, 241, 175, 52), (790, 238, 170, 50), (1010, 241, 150, 46)):
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill="#FFFFFF")
    _paste_header_character(image)
    title_x = width // 2
    draw.rounded_rectangle((355, 40, 725, 118), radius=39, fill="#F7E16B")
    draw.text((title_x, 79), f"{year}.{month:02d}", anchor="mm", font=_month_title_font(52), fill="#2758B0")
    draw.text(
        (title_x, 170), calendar.month_name[month], anchor="mm",
        font=_month_title_font(94), fill="#2758B0", stroke_width=8, stroke_fill="#FFFFFF",
    )
    draw.arc((345, 196, 735, 270), start=195, end=340, fill="#F7E16B", width=12)
    # 添付例のように、太さ・角度・動きのある3つのピクトグラムを配置。
    pictogram = "#75A6E2"
    _paste_rotated_pictogram(image, "heart", (852, 70), -9, pictogram)
    _paste_rotated_pictogram(image, "phone", (952, 92), 10, pictogram)
    _paste_rotated_pictogram(image, "video", (913, 172), 3, pictogram)
    # 黄色の短いアクセント線で躍動感を追加。
    # スマホ右上の動き線はピクトグラムと同じ青。
    for points in (((997, 42), (1012, 24)), ((1007, 56), (1029, 50))):
        draw.line(points, fill=pictogram, width=8)
        for px, py in points:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=pictogram)
    # ハート下の2本線は、元の配置から右回りに30度回転。
    accent = "#F7D928"
    for points in (((837, 136), (818, 142)), ((849, 145), (838, 161))):
        draw.line(points, fill=accent, width=8)
        for px, py in points:
            draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=accent)

    weekdays = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
    grid_top = header_h + weekday_h
    cell_w = (width - margin * 2 - gap * 6) // 7
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    cell_h = (height - grid_top - margin - gap * (len(weeks) - 1)) // len(weeks)

    for col, label in enumerate(weekdays):
        x0 = margin + col * (cell_w + gap)
        fill = "#FF6B78" if col == 0 else "#2F91ED" if col == 6 else "#FFFFFF"
        fg = "#FFFFFF" if col in (0, 6) else "#075FB9"
        draw.rounded_rectangle((x0, header_h, x0 + cell_w, header_h + 62), radius=22, fill=fill, outline="#74B9F3", width=2)
        draw.text((x0 + cell_w // 2, header_h + 32), label, anchor="mm", font=_rounded_font(31), fill=fg)

    by_day: Dict[int, List[Dict[str, Any]]] = {}
    for event in events:
        day = _event_day(event)
        if day:
            by_day.setdefault(day, []).append(event)
    for day_events in by_day.values():
        day_events.sort(key=lambda e: str(e.get("time", "")))

    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            x0 = margin + col * (cell_w + gap)
            y0 = grid_top + row * (cell_h + gap)
            x1, y1 = x0 + cell_w, y0 + cell_h
            if not day:
                draw.rounded_rectangle((x0, y0, x1, y1), radius=20, fill="#FFFFFF", outline="#C5DDF2", width=2)
                continue

            day_events = by_day.get(day, [])
            base_category = classify_event(day_events[0]) if day_events else "その他"
            day_fill: Any = colors[base_category]
            # 「日の背景にも適用」にチェックした予定があれば、その予定の背景で日全体を塗る。
            for day_event in day_events:
                if day_event.get("_calendar_apply_day_background") and day_event.get("_calendar_background_color"):
                    day_fill = event_background_fill(day_event, colors[classify_event(day_event)])
                    break
            _fill_rounded(image, (x0, y0, x1, y1), 20, day_fill, outline="#C5DDF2", width=2)
            is_holiday = _is_japanese_holiday(year, month, day)
            day_color = "#E92E3C" if col == 0 or is_holiday else "#07518D" if col == 6 else "#111827"
            draw.text((x0 + cell_w // 2, y0 + 28), str(day), anchor="mm", font=_rounded_font(42), fill=day_color)

            card_top = y0 + 54
            card_bottom_limit = y1 - 8
            visible_events, card_boxes = _visible_event_layout(day_events, card_top, card_bottom_limit)

            for idx, event in enumerate(visible_events):
                cy, card_bottom = card_boxes[idx]
                category = classify_event(event)
                event_color: Any = colors[category]
                if category == "その他" and event.get("_calendar_background_color"):
                    event_color = event_background_fill(event, colors[category])
                _fill_rounded(image, (x0 + 7, cy, x1 - 7, card_bottom), 13, event_color, outline="#FFFFFF", width=2)
                title_lines = _event_text_lines(event, max_chars=7)
                compact_card = len(day_events) > 1 and card_bottom - cy < 180
                custom_max_lines = event.get("_calendar_max_lines")
                if custom_max_lines is not None:
                    try:
                        title_lines = title_lines[:max(1, min(10, int(custom_max_lines)))]
                    except (TypeError, ValueError):
                        pass
                elif compact_card:
                    if category in ("成果報告", "週報提出"):
                        title_lines = title_lines[:2]
                    else:
                        # 省略記号や講師名の欠落を避け、最大6行まで全文を表示する。
                        title_lines = title_lines[:6]
                card_height = card_bottom - cy
                time_text = str(event.get("time", "") or "")
                if category in ("成果報告", "週報提出") and card_height < 105:
                    time_text = ""
                show_time = bool(time_text and time_text != "00:00")
                minimum_icon_height = 105 if compact_card else 150
                has_icon_space = card_height >= minimum_icon_height
                icon_size = 38 if compact_card else min(70, card_height - 12)
                icon_y = card_bottom - icon_size - 6
                if show_time:
                    if compact_card and has_icon_space:
                        time_y = card_bottom - 58
                    else:
                        time_y = card_bottom - (100 if has_icon_space else 20)
                    title_bottom_limit = time_y - 15
                elif has_icon_space:
                    title_bottom_limit = icon_y - 6
                else:
                    title_bottom_limit = card_bottom - 6
                try:
                    title_font_size = max(8, min(28, int(event.get("_calendar_font_size"))))
                except (TypeError, ValueError):
                    if category in ("成果報告", "週報提出"):
                        title_font_size = 16
                    else:
                        title_font_size = 12 if compact_card else 17
                if category in ("成果報告", "週報提出") and card_height < 90:
                    text_y = cy + 4
                else:
                    text_y = cy + 8
                center_x = x0 + cell_w // 2
                time_font = _event_font(16 if compact_card else 19)
                if show_time:
                    time_top = draw.textbbox(
                        (center_x, time_y), time_text, anchor="mm", font=time_font,
                    )[1]
                    safe_title_bottom = time_top - 7
                else:
                    safe_title_bottom = title_bottom_limit

                def measured_title_bottom(font_size):
                    """空行を含むタイトル全体の、実際の描画下端を返す。"""
                    font = _event_font(font_size)
                    step = font_size + 3
                    bottom = text_y
                    for line_index, line in enumerate(title_lines):
                        line_y = text_y + line_index * step
                        if line:
                            bottom = max(
                                bottom,
                                _event_line_bottom(
                                    draw, center_x, line_y, line, font, font_size,
                                ),
                            )
                        else:
                            bottom = max(bottom, line_y + step)
                    return bottom

                # 初期表示だけは、開催時間や画像へ接触しなくなるまで自動縮小する。
                # 編集画面で文字サイズを変更した場合はユーザー指定を最優先し、
                # 重なりが生じても指定サイズのまま描画する。
                if not bool(event.get("_calendar_font_size_manual")):
                    while (
                        title_font_size > 6
                        and title_lines
                        and measured_title_bottom(title_font_size) > safe_title_bottom
                    ):
                        title_font_size -= 1
                title_font = _event_font(title_font_size)
                title_step = title_font_size + 3

                # 予定名は、カード上端から開催時間・画像枠の直前までの
                # 利用可能な領域内で上下中央に配置する。
                if title_lines:
                    title_area_top = cy + 4
                    drawn_title_height = max(
                        title_step,
                        measured_title_bottom(title_font_size) - text_y,
                    )
                    available_title_height = max(
                        drawn_title_height,
                        safe_title_bottom - title_area_top,
                    )
                    text_y = title_area_top + max(
                        0,
                        (available_title_height - drawn_title_height) // 2,
                    )
                for line in title_lines:
                    _draw_event_line(
                        draw,
                        x0 + cell_w // 2,
                        text_y,
                        line,
                        title_font,
                        title_font_size,
                        "#101A2E",
                    )
                    text_y += title_step
                if show_time:
                    draw.text(
                        (x0 + cell_w // 2, time_y), time_text, anchor="mm",
                        font=time_font, fill="#101A2E",
                    )

                # 編集画面で予定ごとに登録した画像を最優先で使用する。
                event_image_key = str(event.get("_calendar_image_key", "") or "")
                # 予定ごとに選んだ写真は色を変えず、そのまま円形・四角形へ切り抜く。
                source = _read_image(
                    individual_images.get(event_image_key),
                    remove_background=bool(event.get("_calendar_remove_background")),
                )
                instagram_url = str(event.get("instagram_url", "") or "")
                if source is None and instagram_url:
                    source = _read_image(profile_images.get(instagram_url), remove_background=False)
                if source is None:
                    source = _read_image(illustrations.get(category))
                if has_icon_space:
                    icon_x = x0 + (cell_w - icon_size) // 2
                    if category in ("オフ会", "オン会"):
                        if source is not None:
                            fitted = ImageOps.fit(
                                source.convert("RGBA"), (icon_size, icon_size),
                                method=Image.Resampling.LANCZOS,
                            )
                            mask = Image.new("L", (icon_size, icon_size), 0)
                            ImageDraw.Draw(mask).rounded_rectangle(
                                (0, 0, icon_size - 1, icon_size - 1), radius=8, fill=255
                            )
                            fitted.putalpha(ImageChops.multiply(fitted.getchannel("A"), mask))
                            image.alpha_composite(fitted, (icon_x, icon_y))
                        else:
                            draw.rounded_rectangle(
                                (icon_x - 3, icon_y - 3, icon_x + icon_size + 3, icon_y + icon_size + 3),
                                radius=11, fill="#FFFFFF", outline="#D4E4F2", width=2,
                            )
                    else:
                        if source is not None:
                            icon = _circle_image(source, icon_size)
                            image.alpha_composite(icon, (icon_x, icon_y))
                        else:
                            # 未登録時だけ、画像を追加できる位置を示す枠を残す。
                            draw.ellipse(
                                (icon_x - 3, icon_y - 3, icon_x + icon_size + 3, icon_y + icon_size + 3),
                                fill="#FFFFFF", outline="#D4E4F2", width=2,
                            )

            if len(day_events) > 3:
                draw.text((x1 - 10, y1 - 10), f"+{len(day_events) - 3}", anchor="rs", font=_font(18, True), fill="#075FB9")

    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
