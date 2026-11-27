"""コピーした画像を貼り付け（Ctrl+V / ⌘V）で受け取るStreamlitコンポーネント。"""

import base64
import binascii
from pathlib import Path

import streamlit.components.v1 as components


_component = components.declare_component(
    "snsclub_paste_image",
    path=str(Path(__file__).parent / "frontend"),
)


class PastedImage:
    """st.file_uploader の戻り値と同じように getvalue() / name で扱える貼り付け画像。"""

    def __init__(self, data: bytes, name: str, nonce: str):
        self._data = data
        self.name = name
        self.nonce = nonce

    def getvalue(self) -> bytes:
        return self._data


def paste_image(key: str, label: str = "", height: int = 120):
    """貼り付けられた画像を PastedImage で返す。まだ貼り付けがなければ None。

    同じ貼り付けは再実行のたびに同じ nonce で返るため、呼び出し側で
    処理済みかどうかを nonce で判定すること。
    """
    value = _component(label=label, height=height, key=key, default=None)
    if not isinstance(value, dict) or not value.get("data"):
        return None
    try:
        data = base64.b64decode(str(value["data"]), validate=True)
    except (binascii.Error, ValueError):
        return None
    return PastedImage(data, str(value.get("name") or "pasted.png"), str(value.get("nonce") or ""))
