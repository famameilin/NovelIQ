"""诊断工作按裁定「复用标注工具」「没权限」承接人物/关系/对话案例处置写入

标注语义写入工具工厂原样复用：write_entity / write_relation / write_dialogue 的
签名、yaml 校验、回执与拒绝语义与标注阶段完全同形；承接账本带 diagnosis_open
阶段进闸（annotation.ledger._require_writable），事实端点解析与图登记复用
FactGraph 既有身份金链，不另造第二套写入语义。
"""

from __future__ import annotations

from typing import Any

CASE_WRITE_TOOL_NAMES = ("write_entity", "write_relation", "write_dialogue")


def build_case_write_tools(query_service: Any, ledger: Any) -> list[Any]:
    """从标注语义写入工具工厂逐名复用三个域的写入工具"""
    from src.agents.annotation.tool_factories import build_annotation_tools

    built = {candidate.name: candidate for candidate in build_annotation_tools(query_service, ledger)}
    return [built[name] for name in CASE_WRITE_TOOL_NAMES]
