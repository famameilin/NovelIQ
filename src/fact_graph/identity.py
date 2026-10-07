"""事实图关系稳定身份，领域规则不由数据库仓储解释"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5


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
