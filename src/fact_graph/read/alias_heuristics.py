"人物别名启发式消歧（高精度子串/姓氏片段规则）"

from __future__ import annotations

from collections.abc import Sequence

from src.storage.records.graph import EntitySnapshotRow


def looks_like_alias_name(left: str, right: str) -> bool:
    """子串包含 + 短名长度 >=2：可捕获 贺伯安/伯安 这类别名。"""
    if not left or not right or left == right:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) < 2:
        return False
    return shorter in longer


def find_heuristic_character_edges(
    entities: Sequence[EntitySnapshotRow],
) -> list[tuple[str, str]]:
    """
    返回基于确定性名称规则的可疑同一人物边。

    边端点按 entity_id 字典序小到大排序（uuid 主键，确定性不变）；只处理 entity_type=character。
    """
    chars = [
        entity
        for entity in entities
        if getattr(entity, "entity_type", "character") == "character"
        and getattr(entity, "entity_id", None) is not None
        and getattr(entity, "name", None)
    ]
    edges: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(chars)):
        for j in range(i + 1, len(chars)):
            left = chars[i]
            right = chars[j]
            if not looks_like_alias_name(left.name, right.name):
                continue
            a, b = sorted(
                (str(left.entity_id), str(right.entity_id)),
            )
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append((a, b))
    return edges
