"""
创建时间: 2026-04-23
任务: annotation-projector-runtime-landing
说明: Phase4 关系抽取结果投影器，负责 RelationExtractionResult 到 RelationChangeSnapshot 的转换。
"""

from __future__ import annotations

from src.config.constants import SYMMETRIC_RELATION_TYPES
from src.models.local.schema import RelationChangeSnapshot, RelationExtractionResult

_DEFAULT_RELATION_CONFIDENCE: float = 0.85


def convert_relation_result_to_snapshots(
    result: RelationExtractionResult,
    source_model: str,
) -> list[RelationChangeSnapshot]:
    """
    将 LLM 关系抽取结果转换为关系变化快照。

    创建时间: 2026-04-23
    任务: annotation-projector-runtime-landing
    新建原因: 将 relation 去重、方向性与对称边扩展从 Phase4 调用层迁到 projector。
    """
    snapshots: list[RelationChangeSnapshot] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for record in result.relations:
        key = (record.from_name, record.to_name, record.type)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        snapshots.append(
            RelationChangeSnapshot(
                from_name=record.from_name,
                to_name=record.to_name,
                type=record.type,
                change=record.change,
                evidence=record.evidence,
                confidence=_DEFAULT_RELATION_CONFIDENCE,
                source_model=source_model,
                projection_status="pending",
                directionality="symmetric" if record.type in SYMMETRIC_RELATION_TYPES else "directed",
            )
        )

        if record.type in SYMMETRIC_RELATION_TYPES and record.from_name != record.to_name:
            reverse_key = (record.to_name, record.from_name, record.type)
            if reverse_key not in seen_keys:
                seen_keys.add(reverse_key)
                snapshots.append(
                    RelationChangeSnapshot(
                        from_name=record.to_name,
                        to_name=record.from_name,
                        type=record.type,
                        change=record.change,
                        evidence=record.evidence,
                        confidence=_DEFAULT_RELATION_CONFIDENCE,
                        source_model=source_model,
                        projection_status="pending",
                        directionality="symmetric",
                    )
                )

    return snapshots
