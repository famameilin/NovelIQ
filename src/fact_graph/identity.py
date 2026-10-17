"""事实图关系稳定身份，领域规则不由数据库仓储解释"""

from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.fact_graph.vocabulary import RELATION_DEFINITIONS


def relation_id(
    run_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relation_type: str,
    directionality: str,
) -> str:
    """双向关系按端点排序生成身份，与投递或物化顺序无关"""
    left_id, right_id = from_entity_id, to_entity_id
    if directionality == "bidirectional" and left_id > right_id:
        left_id, right_id = right_id, left_id
    return str(uuid5(NAMESPACE_URL, f"noveliq:relation:{run_id}:{left_id}:{right_id}:{relation_type}:{directionality}"))


def comparison_relation_pair(
    from_entity_id: Any,
    to_entity_id: Any,
    relation_type: str,
) -> tuple[Any, Any, str]:
    """比对用关系端点对：双向类型与 relation_id 同规则按端点排序

    2026-10-17 双向关系的身份与投递方向无关（relation_id 已排序归一化），保存核查
    若仍按投递方向逐字比对，同一对端点换向重投会与既有行不等，把正常保存判成
    "结果不一致"（resume 重跑章节时模型换向即触发）。定向类型的两端先后是语义本身，
    保持原序不归一化。
    """
    definition = RELATION_DEFINITIONS.get(relation_type)
    if (
        definition is not None
        and definition["directionality"] == "bidirectional"
        and from_entity_id is not None
        and to_entity_id is not None
        and str(from_entity_id) > str(to_entity_id)
    ):
        return to_entity_id, from_entity_id, relation_type
    return from_entity_id, to_entity_id, relation_type
