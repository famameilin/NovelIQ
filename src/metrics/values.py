"""所属领域的字段契约与结果处理"""

from __future__ import annotations


def read_emotion_score(value: object) -> int:
    """读取情绪分值合同：未填写视为中性 0，非 -2..2 整数直接报错"""
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and -2 <= value <= 2:
        return value
    raise ValueError(f"emotion={value!r}，应为 -2..2 整数或未填写的 None")
