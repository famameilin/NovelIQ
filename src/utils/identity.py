"""标注产物的服务端稳定身份"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any
from uuid import NAMESPACE_URL, uuid5


def _normalized(value: Any, *, fold_text: bool) -> Any:
    if isinstance(value, str):
        text = unicodedata.normalize("NFC", value).strip()
        return text.casefold() if fold_text else text
    if isinstance(value, dict):
        return {str(key): _normalized(item, fold_text=fold_text) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalized(item, fold_text=fold_text) for item in value]
    return value


def stable_digest(*parts: Any, fold_text: bool = False) -> str:
    """对结构化输入使用固定 JSON 顺序生成幂等哈希"""
    payload = _normalized(parts, fold_text=fold_text)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    """原文按实际 UTF-8 字节冻结，空白及 Unicode 组合形式也是输入的一部分"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_uuid(*parts: Any) -> str:
    """需要 UUID 外键的本地节点用稳定命名空间生成身份"""
    return str(uuid5(NAMESPACE_URL, stable_digest(*parts, fold_text=True)))
