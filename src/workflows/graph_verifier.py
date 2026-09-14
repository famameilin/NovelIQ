"""
章节图一致性验证器：孤儿别名检测

说明: 检测无同一人物边但邻居高度重叠的角色对，生成待仲裁 entity_alias 案例。
不自动建边；边是否建立、建立什么关系一律由案例仲裁决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_DNS, uuid5

from sqlalchemy.orm import Session

from src.agents.annotation.schema import PendingCase
from src.storage.models import ChapterBoundary
from src.storage.repositories.graph import GraphRepository

_NEIGHBOR_OVERLAP_THRESHOLD = 0.4
_MIN_SHARED_NEIGHBOR_COUNT = 2
_MAX_ALIAS_PAIRS_PER_RUN = 10
# 2026-09-13 枢纽角色判定：与半数以上角色（且至少 4 个）相连的节点不参与身份作证
_HUB_DEGREE_MIN = 4


@dataclass(frozen=True, slots=True)
class AliasSuspicion:
    """2026-08-09 用于保存单个疑似同一人物角色对"""

    name_a: str
    name_b: str
    overlap: float
    anchor_chapter_id: int


def detect_alias_suspicions(
    session: Session,
    *,
    chapter_boundary: ChapterBoundary,
) -> list[AliasSuspicion]:
    """2026-08-09 用于检测共享邻居高度重叠的角色对，疑似同一人物进案例池仲裁

    2026-09-13 修假阳性（run c80105cc 实测 10 对全假、其中 6 对到 run 死时仍是
    active，并在每章 search_graph 回执里被反复点名，两章烧掉约 2 万字符思考）：
    四条结构性排除，均由该 run 的图谱形状坐实——假阳性共享的邻居恰好是
    「贺伯安（主角，连了 8 个角色）+ 贺家军（组织）」这两个枢纽节点，
    该图 10 对按新规则重放检出 0 对。规则：
    ① 邻居只算角色：共享一个组织/地点（都在贺家军、都在贺府）不是身份证据；
    ② 枢纽邻居不参与作证：与半数以上角色（且至少 4 个）相连的节点，任何配角对
       都会共享它；
    ③ 共享邻居按度数加权（1/deg）：共享两个"人人都认识的"远不如共享两个独有
       邻居有说服力；阈值仍是 0.4，作用在加权重叠上；
    ④ 两端已有直接关系的对直接排除：亲戚/盟友/敌对不可能是同一个人
       （同一人物边本身已由并查集排除）。
    宁缺勿滥：这是给模型的待裁决噪声，误报的代价是每章重复推理，漏报则由
    写者自己的「同一人物」边通道兜底。
    """
    graph_repo = GraphRepository(session)
    entities = [row for row in graph_repo.fetch_entity_snapshots(chapter_boundary) if row.entity_type == "character"]
    relations = graph_repo.fetch_relation_snapshots(chapter_boundary, active_only=True)

    neighbors: dict[int, set[int]] = {}
    parent: dict[int, int] = {}
    direct_pairs: set[frozenset[int]] = set()

    def find(node: int) -> int:
        if parent.get(node, node) != node:
            parent[node] = find(parent[node])
        return parent[node]

    def union(left: int, right: int) -> None:
        parent.setdefault(left, left)
        parent.setdefault(right, right)
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for relation in relations:
        from_id = int(relation.from_entity_id)
        to_id = int(relation.to_entity_id)
        if relation.relation_semantics == "same_character":
            union(from_id, to_id)
            continue
        direct_pairs.add(frozenset((from_id, to_id)))
        neighbors.setdefault(from_id, set()).add(to_id)
        neighbors.setdefault(to_id, set()).add(from_id)

    character_ids = [int(row.entity_id) for row in entities]
    for entity_id in character_ids:
        parent.setdefault(entity_id, entity_id)

    # ① 邻居只算角色：组织/地点/物品的共享关系不构成身份证据
    character_id_set = set(character_ids)
    for entity_id in list(neighbors):
        neighbors[entity_id] = {node for node in neighbors[entity_id] if node in character_id_set}
    # ② 枢纽邻居不参与作证：与半数以上角色（至少 4 个）相连的是主角/组织代言人这类
    #    节点，任何配角对都会共享它们——run c80105cc 的 6 对假阳性正是共享同一个主角
    hub_cutoff = max(_HUB_DEGREE_MIN, len(character_ids) / 2)
    for entity_id in list(neighbors):
        neighbors[entity_id] = {
            node for node in neighbors[entity_id] if len(neighbors.get(node, ())) < hub_cutoff
        }
    # ③ 权重=1/度数：共享两个"人人都认识的"远不如共享两个独有邻居有说服力
    weights = {
        entity_id: 1.0 / len(neighbors[entity_id])
        for entity_id in character_ids
        if neighbors.get(entity_id)
    }

    names_by_id = {int(row.entity_id): row.name for row in entities}
    last_seen_by_id = {int(row.entity_id): row.last_seen_chapter for row in entities}

    suspicions: list[AliasSuspicion] = []
    for index, left_id in enumerate(character_ids):
        left_neighbors = neighbors.get(left_id, set())
        if len(left_neighbors) < _MIN_SHARED_NEIGHBOR_COUNT:
            continue
        for right_id in character_ids[index + 1 :]:
            if find(left_id) == find(right_id):
                continue
            # ③ 两端已有直接关系（非同一人物语义）：不可能是同一个人
            if frozenset((left_id, right_id)) in direct_pairs:
                continue
            right_neighbors = neighbors.get(right_id, set())
            if len(right_neighbors) < _MIN_SHARED_NEIGHBOR_COUNT:
                continue
            shared = left_neighbors & right_neighbors
            if len(shared) < _MIN_SHARED_NEIGHBOR_COUNT:
                continue
            weight_union = sum(weights.get(node, 0.0) for node in left_neighbors | right_neighbors)
            if weight_union <= 0.0:
                continue
            overlap = sum(weights.get(node, 0.0) for node in shared) / weight_union
            if overlap < _NEIGHBOR_OVERLAP_THRESHOLD:
                continue
            suspicions.append(
                AliasSuspicion(
                    name_a=names_by_id[left_id],
                    name_b=names_by_id[right_id],
                    overlap=round(overlap, 3),
                    anchor_chapter_id=min(
                        last_seen_by_id[left_id],
                        last_seen_by_id[right_id],
                    ),
                )
            )
    suspicions.sort(key=lambda item: item.overlap, reverse=True)
    return suspicions[:_MAX_ALIAS_PAIRS_PER_RUN]


def build_alias_pending_cases(
    session: Session,
    *,
    run_id: str,
    chapter_boundary: ChapterBoundary,
    existing_target_keys: set[str],
) -> list[PendingCase]:
    """2026-08-09 用于把疑似同一人物对转换为待仲裁案例"""
    pending_cases: list[PendingCase] = []
    for suspicion in detect_alias_suspicions(session, chapter_boundary=chapter_boundary):
        target_key = uuid5(NAMESPACE_DNS, f"{run_id}:entity_alias:{suspicion.name_a}:{suspicion.name_b}").hex
        if target_key in existing_target_keys:
            continue
        pending_cases.append(
            PendingCase(
                type="entity_alias",
                chunk_id=suspicion.anchor_chapter_id,
                keys=[suspicion.name_a, suspicion.name_b, "同一人物"],
                description=(
                    f"疑似同一人物：{suspicion.name_a} 与 {suspicion.name_b} "
                    f"邻居重合度 {suspicion.overlap:.0%}（按邻居稀有度加权），请查阅原文确认"
                )[:100],
                target_key=target_key,
                target_ref={
                    "kind": "entity_alias",
                    "chunk_id": suspicion.anchor_chapter_id,
                    "name_a": suspicion.name_a,
                    "name_b": suspicion.name_b,
                },
            )
        )
    return pending_cases


__all__ = ["AliasSuspicion", "build_alias_pending_cases", "detect_alias_suspicions"]
