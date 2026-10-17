"""四类引用共用的正式身份投影，不改写来源记录"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.fact_graph.read.alias import AliasResolution, build_alias_resolution
from src.storage.repositories.graph.repository import (
    ChapterBoundary,
    EntitySnapshotRow,
    GraphRepository,
)


def relation_projection_key(
    left: str, right: str, relation_type: str, directionality: str
) -> tuple[str, str, str]:
    """引用去重沿用正式双向规则，只归一比较键，不改变已有边的展示方向"""
    if directionality == "bidirectional":
        left, right = sorted((left, right))
    return left, right, relation_type


@dataclass(frozen=True)
class EntityReferenceProjection:
    entities: dict[str, EntitySnapshotRow]
    resolution: AliasResolution

    @classmethod
    def load(
        cls, session: Session, run_id: str, *, boundary: ChapterBoundary | None = None
    ) -> EntityReferenceProjection:
        """明确章节边界时不使用后章身份断言；全书查询使用最新已保存边界

        已删除/不存在的运行与尚无已保存边界同样按空投影处理，读口不为已删运行报错。
        """
        repository = GraphRepository(session)
        if boundary is None and repository.run_exists(run_id):
            boundary = repository.resolve_chapter_boundary(run_id)
        entities = repository.fetch_entity_snapshots(boundary) if boundary else []
        relations = repository.fetch_relation_snapshots(boundary, active_only=False) if boundary else []
        return cls({row.entity_id: row for row in entities}, build_alias_resolution(relations, entities=entities))

    def entity(self, reference: dict[str, Any]) -> dict[str, Any]:
        """未知引用原样保留，由章末核对定位；已确认身份同时统一 id、名字和大类"""
        result = dict(reference)
        identifier = self.resolution.resolve_entity_id(reference.get("entity_id"))
        entity = self.entities.get(identifier or "")
        if entity is not None:
            result.update(entity_id=entity.entity_id, name=entity.name, entity_type=entity.entity_type)
        return result

    def participants(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """同身份同角色的完全重复支持只显示一次，不同动作或情绪仍保留原陈述"""
        result: list[dict[str, Any]] = []
        for source in participants:
            participant = deepcopy(source)
            participant["entity"] = self.entity(source["entity"])
            if participant not in result:
                result.append(participant)
        return result

    def tags(self, entity_id: str) -> list[str]:
        """已确认身份下保留各实体来源的有效标签，不复活已被原作者清空的标签"""
        representative = self.resolution.resolve_entity_id(entity_id)
        return list(
            dict.fromkeys(
                tag
                for identifier, entity in sorted(self.entities.items())
                if self.resolution.resolve_entity_id(identifier) == representative
                for tag in entity.tags
            )
        )
