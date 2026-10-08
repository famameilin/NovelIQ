"""正式事件的文档位置，供投影、连续性订正和读模型统一使用"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.storage.models import AnalysisOutput


def formal_event_ordinals(annotations: Iterable[AnalysisOutput]) -> dict[str, int]:
    """同段事件按不可变章标注的写入序号排序，不从命令哈希推断顺序"""
    return {
        event["node_id"]: ordinal
        for annotation in annotations
        for ordinal, event in enumerate(annotation.payload["events"])
    }
