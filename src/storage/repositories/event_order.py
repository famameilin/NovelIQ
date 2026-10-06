"""正式事件的文档位置，供投影、连续性订正和读模型统一使用"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.storage.models import AnalysisOutput, EventNode


def formal_event_ordinals(annotations: Iterable[AnalysisOutput]) -> dict[str, int]:
    """同段事件按不可变章标注的写入序号排序，不从命令哈希推断顺序"""
    return {
        event["node_id"]: ordinal
        for annotation in annotations
        for ordinal, event in enumerate(annotation.payload["events"])
    }


def event_position(node: EventNode, ordinals: Mapping[str, int]) -> tuple[int, int, int]:
    """段落起点相同时使用正式序号，不伪造原文字符偏移"""
    return node.chapter_order, node.char_start, ordinals[node.event_id]
