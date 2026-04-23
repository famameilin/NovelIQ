"""
Phase4 relation projector 单元测试。

创建时间: 2026-04-23
任务: annotation-projector-runtime-landing
说明: 覆盖 RelationExtractionResult 到 RelationChangeSnapshot 的薄投影边界。
"""

from __future__ import annotations

from src.config.constants import SYMMETRIC_RELATION_TYPES
from src.models.local.annotation.projectors.relation import convert_relation_result_to_snapshots
from src.models.local.schema import RelationExtractionResult, RelationRecord


def _relation(from_name: str, to_name: str, type: str, change: str = "新建") -> RelationRecord:
    """创建 projector 测试用 RelationRecord。"""
    return RelationRecord.model_validate(
        {
            "from": from_name,
            "to": to_name,
            "type": type,
            "change": change,
            "evidence": "证据",
        }
    )


def test_convert_relation_result_deduplicates_same_key() -> None:
    """相同 from/to/type 的关系只保留一次。"""
    result = convert_relation_result_to_snapshots(
        RelationExtractionResult(relations=[_relation("张三", "李四", "敌对"), _relation("张三", "李四", "敌对")]),
        "model-a",
    )

    assert len(result) == 1
    assert result[0].source_model == "model-a"


def test_convert_relation_result_generates_symmetric_reverse_edges() -> None:
    """对称关系应生成反向边。"""
    relation_type = next(iter(SYMMETRIC_RELATION_TYPES))
    result = convert_relation_result_to_snapshots(
        RelationExtractionResult(relations=[_relation("张三", "李四", relation_type)]),
        "model-a",
    )

    assert {(item.from_name, item.to_name) for item in result} == {("张三", "李四"), ("李四", "张三")}
    assert all(item.directionality == "symmetric" for item in result)


def test_convert_relation_result_does_not_duplicate_self_loop_or_directed_reverse() -> None:
    """自环对称关系不补反向边，有向关系不补反向边。"""
    symmetric_type = next(iter(SYMMETRIC_RELATION_TYPES))
    self_loop = convert_relation_result_to_snapshots(
        RelationExtractionResult(relations=[_relation("张三", "张三", symmetric_type)]),
        "model-a",
    )
    directed = convert_relation_result_to_snapshots(
        RelationExtractionResult(relations=[_relation("张三", "李四", "敌对")]),
        "model-a",
    )

    assert len(self_loop) == 1
    assert len(directed) == 1
    assert directed[0].directionality == "directed"
