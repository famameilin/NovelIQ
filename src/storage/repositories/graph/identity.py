"""读模型的实体规范名与关系稳定身份"""

from __future__ import annotations

import unicodedata
from uuid import NAMESPACE_URL, uuid5


def normalized_name(value: str) -> str:
    """实体名称按 NFC 与大小写折叠统一索引"""
    return unicodedata.normalize("NFC", value).strip().casefold()


def relation_id(
    run_id: str, from_entity_id: str, to_entity_id: str,
    relation_type: str, directionality: str,
) -> str:
    """双向关系按端点排序生成身份，与投递或物化顺序无关"""
    left_id, right_id = from_entity_id, to_entity_id
    if directionality == "bidirectional" and left_id > right_id:
        left_id, right_id = right_id, left_id
    return str(uuid5(NAMESPACE_URL, f"noveliq:relation:{run_id}:{left_id}:{right_id}:{relation_type}:{directionality}"))
