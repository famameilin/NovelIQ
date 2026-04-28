"""
标注数据协议接口

使用 AnnotationRecord 替代动态字典，收窄协议边界
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .types import AnnotationRecord


@runtime_checkable
class AnnotationRepositoryProtocol(Protocol):
    """
    标注数据接口

    管理小说标注数据的存储和检索
    """

    def get_annotations(self, novel_id: str) -> list[AnnotationRecord]:
        """
        获取所有标注

        Args:
            novel_id: 小说ID

        Returns:
            标注列表
        """
        ...

    def get_annotation_by_chunk(self, novel_id: str, chunk_id: int) -> AnnotationRecord | None:
        """
        按分块获取标注

        Args:
            novel_id: 小说ID
            chunk_id: 分块ID

        Returns:
            标注字典，不存在则返回 None
        """
        ...

    def insert_annotations(self, novel_id: str, annotations: Sequence[AnnotationRecord]) -> None:
        """
        批量插入标注

        Args:
            novel_id: 小说ID
            annotations: 标注列表
        """
        ...

    def clear_annotations(self, novel_id: str) -> None:
        """
        清空标注数据

        Args:
            novel_id: 小说ID
        """
        ...
