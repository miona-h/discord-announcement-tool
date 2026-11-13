#!/usr/bin/env python3
"""Googleカレンダーの予定から月間カレンダー画像を生成する。"""

from __future__ import annotations

import calendar
import html
import io
import os
import re
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont, ImageOps

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
    """元画像に近い「種別 → ジャンル → 講師名」の順で表示文言を作る。"""
    category = classify_event(event)
    summary = _display_title(event)
    event_type = str(event.get("event_type", "") or "")
    genre = str(event.get("genre", "") or "").strip()
    teacher = str(event.get("teacher_name", "") or "").strip()
    lines: List[str] = []

    if category == "グルコン":
        if "フォロワー別" in f"{summary} {event_type}":
            lines.extend(["フォロワー別", "グルコン"])
        else:
            lines.extend(["ジャンル特化", "グルコン"])
        if genre:
            clean_genre = re.sub(r"^[^\wぁ-んァ-ン一-鿿]+", "", genre).replace("ジャンル", "").strip()
            if clean_genre:
                lines.append(f"【{clean_genre}】")
        else:
            bracket = re.search(r"[【\[]([^】\]]+)[】\]]", summary)
            if bracket:
                label = bracket.group(1).replace("グルコン", "").strip("・ ")
                if label:
                    lines.append(f"【{label}】")
    elif category == "対談":
        talk_type = "生徒対談" if "生徒対談" in f"{summary} {event_type}" else "講師対談"
        lines.append(f"【{talk_type}】")
        lines.append("ゲスト")
    elif category in ("成果報告", "週報提出"):
        if "成果報告" in summary and "週報" in summary:
            lines.extend(["成果報告・", "週報提出"])
        else:
            lines.append(category)
    elif category == "オフ会":
        lines.extend(_wrap_chars(summary, max_chars, 3))
    elif category == "オン会":
        lines.extend(["オン会", "(in Zoom)"] if "zoom" in summary.lower() else ["オン会"])
    else:
        lines.extend(_wrap_chars(summary, max_chars, 3))

    if teacher and teacher not in " ".join(lines):
        lines.extend(_wrap_chars(teacher, max_chars, 2))
    return lines[:6]


def _wrap_chars(text: str, max_chars: int, max_lines: int) -> List[str]:
    compact = re.sub(r"\s+", " ", str(text)).strip()
    lines = [compact[i:i + max_chars] for i in range(0, len(compact), max_chars)] or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def _read_image(data: Optional[bytes]) -> Optional[Image.Image]:
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None


def fetch_instagram_profile_image(instagram_url: str, timeout: int = 6) -> Optional[bytes]:
    """Instagramページの og:image を最善努力で取得する。制限時は None。"""
    if not instagram_url or "instagram.com" not in instagram_url.lower():
        return None
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


def _circle_image(source: Image.Image, size: int) -> Image.Image:
    square = ImageOps.fit(source.convert("RGBA"), (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    out.paste(square, (0, 0), mask)
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
        icon.text((39, 35), "♥", anchor="mm", font=_font(34, True), fill="#FFFFFF")
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
) -> bytes:
    """縦16:9（1080×1920px）のPNGカレンダーを返す。"""
    colors = dict(DEFAULT_CATEGORY_STYLES)
    colors.update(category_colors or {})
    illustrations = category_illustrations or {}
    profile_images = instagram_images or {}

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
        draw.text((x0 + cell_w // 2, header_h + 32), label, anchor="mm", font=_rounded_font(25), fill=fg, stroke_width=1, stroke_fill=fg)

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
            draw.rounded_rectangle((x0, y0, x1, y1), radius=20, fill=colors[base_category], outline="#C5DDF2", width=2)
            is_holiday = _is_japanese_holiday(year, month, day)
            day_color = "#E92E3C" if col == 0 or is_holiday else "#07518D" if col == 6 else "#111827"
            draw.text((x0 + cell_w // 2, y0 + 25), str(day), anchor="mm", font=_rounded_font(33), fill=day_color, stroke_width=1, stroke_fill=day_color)

            card_top = y0 + 54
            visible_events = day_events[:3]
            card_bottom_limit = y1 - 8
            available_height = card_bottom_limit - card_top
            card_boxes = []
            # 成果報告・週報提出＋通常予定の日は、提出案内を上部1/4の帯にする。
            if (
                len(visible_events) == 2
                and classify_event(visible_events[0]) in ("成果報告", "週報提出")
                and classify_event(visible_events[1]) not in ("成果報告", "週報提出")
            ):
                banner_height = max(46, int(available_height * 0.25))
                card_boxes = [
                    (card_top, card_top + banner_height),
                    (card_top + banner_height + 5, card_bottom_limit),
                ]
            else:
                card_space = max(58, available_height // max(1, len(visible_events)))
                for idx in range(len(visible_events)):
                    cy = card_top + idx * card_space
                    card_boxes.append((cy, min(card_bottom_limit, cy + card_space - 5)))

            for idx, event in enumerate(visible_events):
                cy, card_bottom = card_boxes[idx]
                category = classify_event(event)
                draw.rounded_rectangle((x0 + 7, cy, x1 - 7, card_bottom), radius=13, fill=colors[category], outline="#FFFFFF", width=2)
                title_lines = _event_text_lines(event, max_chars=7)
                if len(day_events) > 1:
                    title_lines = title_lines[:3]
                card_height = card_bottom - cy
                if category in ("成果報告", "週報提出") and card_height < 90:
                    text_y = cy + max(4, (card_height - len(title_lines) * 21) // 2)
                else:
                    text_y = cy + 8
                for line in title_lines:
                    draw.text(
                        (x0 + cell_w // 2, text_y), line, anchor="ma",
                        font=_event_font(17), fill="#101A2E",
                    )
                    text_y += 21
                time_text = str(event.get("time", "") or "")
                if time_text and time_text != "00:00":
                    has_icon_space = card_bottom - cy >= 150
                    time_y = card_bottom - (100 if has_icon_space else 20)
                    draw.text(
                        (x0 + cell_w // 2, time_y), time_text, anchor="mm",
                        font=_event_font(19), fill="#101A2E",
                    )

                source = None
                instagram_url = str(event.get("instagram_url", "") or "")
                if instagram_url:
                    source = _read_image(profile_images.get(instagram_url))
                if source is None:
                    source = _read_image(illustrations.get(category))
                if card_bottom - cy >= 150:
                    icon_size = min(70, card_bottom - cy - 12)
                    icon_x = x0 + (cell_w - icon_size) // 2
                    icon_y = card_bottom - icon_size - 6
                    if category in ("オフ会", "オン会"):
                        # 会場・交流会イラストは、参考画像と同じ角丸四角フレーム。
                        draw.rounded_rectangle(
                            (icon_x - 3, icon_y - 3, icon_x + icon_size + 3, icon_y + icon_size + 3),
                            radius=11, fill="#FFFFFF", outline="#D4E4F2", width=2,
                        )
                        if source is not None:
                            fitted = ImageOps.fit(
                                source.convert("RGBA"), (icon_size, icon_size),
                                method=Image.Resampling.LANCZOS,
                            )
                            mask = Image.new("L", (icon_size, icon_size), 0)
                            ImageDraw.Draw(mask).rounded_rectangle(
                                (0, 0, icon_size - 1, icon_size - 1), radius=8, fill=255
                            )
                            image.paste(fitted, (icon_x, icon_y), mask)
                    else:
                        # 講師画像は常に丸フレームを表示し、未登録時も追加位置が分かるようにする。
                        draw.ellipse(
                            (icon_x - 3, icon_y - 3, icon_x + icon_size + 3, icon_y + icon_size + 3),
                            fill="#FFFFFF", outline="#D4E4F2", width=2,
                        )
                        if source is not None:
                            icon = _circle_image(source, icon_size)
                            image.alpha_composite(icon, (icon_x, icon_y))

            if len(day_events) > 3:
                draw.text((x1 - 10, y1 - 10), f"+{len(day_events) - 3}", anchor="rs", font=_font(18, True), fill="#075FB9")

    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
