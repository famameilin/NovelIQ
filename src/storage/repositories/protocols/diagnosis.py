"""
创建时间: 2026-03-18
创建者: TraeAI
任务: code-quality-refactor - 拆分protocols.py
说明: 诊断数据协议接口
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DiagnosisRepositoryProtocol(Protocol):
    """
    诊断数据接口

    管理小说诊断数据的存储和检索。
    """

    def get_diagnosis(self, novel_id: str) -> dict[str, Any]:
        """
        获取诊断数据

        Args:
            novel_id: 小说ID

        Returns:
            诊断数据字典
        """
        ...

    def save_diagnosis(self, novel_id: str, diagnosis: dict[str, Any]) -> None:
        """
        保存诊断数据

        Args:
            novel_id: 小说ID
            diagnosis: 诊断数据字典
        """
        ...

    def get_diagnosis_history(self, novel_id: str) -> list[dict[str, Any]]:
        """
        获取诊断历史

        Args:
            novel_id: 小说ID

        Returns:
            诊断历史列表
        """
        ...
