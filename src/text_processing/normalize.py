"""语义文本的 Unicode 与空白规范化"""

import unicodedata


def normalize_semantic_text(value: str, *, label: str) -> str:
    """统一规范化 Agent 提交的人类可读文本"""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    return normalized

