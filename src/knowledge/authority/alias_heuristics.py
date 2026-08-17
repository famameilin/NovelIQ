"""
P11 人物别名启发式消歧（高精度子串/姓氏片段规则）

依据：data/gold_standards/disambiguation/ 金标中“贺伯安→伯安”这类可被子串规则
捕获的别名；对“赵哥→赤甲卫”“灵禽→赤羽炽尾鸡”等 false_merge 不应触发。

当前只做高精度规则，昵称类（如猴子→侯飞白）仍依赖 LLM same_character 声明；
缺失时保留双节点，由离线金标评估持续度量召回缺口。
"""

from __future__ import annotations

from collections.abc import Sequence

from src.storage.repositories.graph.repository import EntitySnapshotRow


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
) -> list[tuple[int, int]]:
    """
    返回基于确定性名称规则的可疑同一人物边。

    边端点按 entity_id 小到大排序；只处理 entity_type=character。
    """
    chars = [
        entity
        for entity in entities
        if getattr(entity, "entity_type", "character") == "character"
        and getattr(entity, "entity_id", None) is not None
        and getattr(entity, "name", None)
    ]
    edges: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for i in range(len(chars)):
        for j in range(i + 1, len(chars)):
            left = chars[i]
            right = chars[j]
            if not looks_like_alias_name(left.name, right.name):
                continue
            a, b = sorted(
                (int(left.entity_id), int(right.entity_id)),
            )
            if (a, b) in seen:
                continue
            seen.add((a, b))
            edges.append((a, b))
    return edges