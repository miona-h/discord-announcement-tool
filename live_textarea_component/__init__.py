"""キー入力後に値を返すStreamlit用の複数行テキスト入力。"""

from pathlib import Path

import streamlit.components.v1 as components


_component = components.declare_component(
    "snsclub_live_textarea",
    path=str(Path(__file__).parent / "frontend"),
)


def live_textarea(label: str, value: str, key: str, height: int = 220, debounce: int = 300) -> str:
    return _component(
        label=label,
        value=value,
        height=height,
        debounce=debounce,
        key=key,
        default=value,
    )
