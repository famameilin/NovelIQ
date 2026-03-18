"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 实体数据协议接口
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class EntityRepositoryProtocol(Protocol):
    """
    实体数据接口

    管理角色、关系等实体的存储和检索。
    """

    def get_characters(self, novel_id: str) -> List[Dict[str, Any]]:
        """
        获取所有角色

        Args:
            novel_id: 小说ID

        Returns:
            角色列表
        """
        ...

    def get_relations(self, novel_id: str) -> List[Dict[str, Any]]:
        """
        获取所有关系

        Args:
            novel_id: 小说ID

        Returns:
            关系列表
        """
        ...

    def get_character_by_name(self, novel_id: str, name: str) -> Dict[str, Any] | None:
        """
        按名称获取角色

        Args:
            novel_id: 小说ID
            name: 角色名称

        Returns:
            角色字典，不存在则返回 None
        """
        ...

    def insert_characters(self, novel_id: str, characters: List[Dict[str, Any]]) -> None:
        """
        批量插入角色

        Args:
            novel_id: 小说ID
            characters: 角色列表
        """
        ...

    def insert_relations(self, novel_id: str, relations: List[Dict[str, Any]]) -> None:
        """
        批量插入关系

        Args:
            novel_id: 小说ID
            relations: 关系列表
        """
        ...
