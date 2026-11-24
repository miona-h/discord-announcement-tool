"""画像ライブラリからカレンダーへドラッグできるStreamlitコンポーネント。"""

from pathlib import Path
import streamlit.components.v1 as components

_component = components.declare_component(
    "snsclub_calendar_drag_preview",
    path=str(Path(__file__).parent / "frontend"),
)


def calendar_drag_preview(calendar_src: str, assets: list[dict], key: str, width: int = 700):
    return _component(
        calendar_src=calendar_src,
        assets=assets,
        width=width,
        key=key,
        default=None,
    )
