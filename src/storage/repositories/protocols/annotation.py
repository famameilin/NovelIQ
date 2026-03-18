"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 标注数据协议接口
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class AnnotationRepositoryProtocol(Protocol):
    """
    标注数据接口

    管理小说标注数据的存储和检索。
    """

    def get_annotations(self, novel_id: str) -> List[Dict[str, Any]]:
        """
        获取所有标注

        Args:
            novel_id: 小说ID

        Returns:
            标注列表
        """
        ...

    def get_annotation_by_chunk(self, novel_id: str, chunk_id: int) -> Dict[str, Any] | None:
        """
        按分块获取标注

        Args:
            novel_id: 小说ID
            chunk_id: 分块ID

        Returns:
            标注字典，不存在则返回 None
        """
        ...

    def insert_annotations(self, novel_id: str, annotations: List[Dict[str, Any]]) -> None:
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
