"""
章节图一致性验证器：孤儿别名检测

说明: 检测无同一人物边但邻居高度重叠的角色对，生成待仲裁 entity_alias 案例。
不自动建边；边是否建立、建立什么关系一律由案例仲裁决定。
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.orm import Session

from src.agents.annotation.schema import PendingCase
from src.storage.models import ChapterBoundary
from src.storage.repositories.graph import GraphRepository

_NEIGHBOR_OVERLAP_THRESHOLD = 0.4
_MIN_SHARED_NEIGHBOR_COUNT = 2
_MAX_ALIAS_PAIRS_PER_RUN = 10


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
    """2026-08-09 用于检测共享邻居高度重叠的角色对，疑似同一人物进案例池仲裁"""
    graph_repo = GraphRepository(session)
    entities = [row for row in graph_repo.fetch_entity_snapshots(chapter_boundary) if row.entity_type == "character"]
    relations = graph_repo.fetch_relation_snapshots(chapter_boundary, active_only=True)

    neighbors: dict[int, set[int]] = {}
    parent: dict[int, int] = {}

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
        neighbors.setdefault(from_id, set()).add(to_id)
        neighbors.setdefault(to_id, set()).add(from_id)

    for entity_id in [int(row.entity_id) for row in entities]:
        parent.setdefault(entity_id, entity_id)

    names_by_id = {int(row.entity_id): row.name for row in entities}
    last_seen_by_id = {int(row.entity_id): row.last_seen_chapter for row in entities}
    character_ids = [int(row.entity_id) for row in entities]

    suspicions: list[AliasSuspicion] = []
    for index, left_id in enumerate(character_ids):
        left_neighbors = neighbors.get(left_id, set())
        if len(left_neighbors) < _MIN_SHARED_NEIGHBOR_COUNT:
            continue
        for right_id in character_ids[index + 1 :]:
            if find(left_id) == find(right_id):
                continue
            right_neighbors = neighbors.get(right_id, set())
            if len(right_neighbors) < _MIN_SHARED_NEIGHBOR_COUNT:
                continue
            shared = left_neighbors & right_neighbors
            if len(shared) < _MIN_SHARED_NEIGHBOR_COUNT:
                continue
            union_size = len(left_neighbors | right_neighbors)
            overlap = len(shared) / union_size
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
        target_key = sha256(f"{run_id}:entity_alias:{suspicion.name_a}:{suspicion.name_b}".encode()).hexdigest()
        if target_key in existing_target_keys:
            continue
        pending_cases.append(
            PendingCase(
                type="entity_alias",
                chunk_id=suspicion.anchor_chapter_id,
                keys=[suspicion.name_a, suspicion.name_b, "同一人物"],
                description=(
                    f"疑似同一人物：{suspicion.name_a} 与 {suspicion.name_b} "
                    f"共享邻居重叠度 {suspicion.overlap:.0%}，请查阅原文确认"
                ),
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
