"""P11 人物别名启发式消歧测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.knowledge.authority.alias import build_alias_resolution
from src.knowledge.authority.alias_heuristics import (
    find_heuristic_character_edges,
    looks_like_alias_name,
)
from src.storage.repositories.graph.repository import EntitySnapshotRow

_GOLD_DIR = Path(__file__).resolve().parents[2] / "data" / "gold_standards" / "disambiguation"


def _entity(
    entity_id: int,
    name: str,
    *,
    entity_type: str = "character",
) -> EntitySnapshotRow:
    return EntitySnapshotRow(
        entity_id=entity_id,
        name=name,
        entity_type=entity_type,
        tags=[],
        attributes={},
        first_seen_chapter=1,
        last_seen_chapter=1,
        state_revision=1,
        state={},
    )


def test_looks_like_alias_name_captures_substring_alias() -> None:
    assert looks_like_alias_name("贺伯安", "伯安") is True
    assert looks_like_alias_name("伯安", "贺伯安") is True


def test_looks_like_alias_name_rejects_false_merge_gold_cases() -> None:
    """金标 false_merge：不得因子串/昵称启发式误合并。"""
    assert looks_like_alias_name("赵哥", "赤甲卫") is False
    assert looks_like_alias_name("灵禽", "赤羽炽尾鸡") is False
    assert looks_like_alias_name("赤甲卫", "伯安") is False
    assert looks_like_alias_name("贺铮", "伯安") is False


def test_looks_like_alias_name_rejects_too_short_and_identical() -> None:
    assert looks_like_alias_name("柳", "柳婉儿") is False
    assert looks_like_alias_name("伯安", "伯安") is False
    assert looks_like_alias_name("", "伯安") is False


def test_find_heuristic_character_edges_only_character_type() -> None:
    entities = [
        _entity(1, "贺伯安"),
        _entity(2, "伯安"),
        _entity(3, "赤羽炽尾鸡", entity_type="creature"),
        _entity(4, "赤羽"),
    ]
    edges = find_heuristic_character_edges(entities)
    assert edges == [(1, 2)]


def test_build_alias_resolution_merges_heuristic_substring_without_llm_edge() -> None:
    """无 same_character 关系时，子串启发式仍可合并 贺伯安→伯安。"""
    entities = [
        _entity(10, "贺伯安"),
        _entity(20, "伯安"),
        _entity(30, "赵哥"),
        _entity(40, "赤甲卫"),
    ]
    resolution = build_alias_resolution([], entities=entities)

    # 贺伯安/伯安 应收敛到同一代表
    assert resolution.resolve_entity_id(10) == resolution.resolve_entity_id(20)
    # 赵哥/赤甲卫 不得误合并
    assert resolution.resolve_entity_id(30) == 30
    assert resolution.resolve_entity_id(40) == 40


def test_gold_should_not_merge_pairs_are_never_heuristic_hits() -> None:
    """遍历金标 should_not_merge：启发式 precision 侧不得误触发。"""
    if not _GOLD_DIR.exists():
        return

    false_positives: list[str] = []
    for path in sorted(_GOLD_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            record = json.loads(line)
            if record.get("judgment") != "should_not_merge":
                continue
            alias = str(record["alias"])
            canonical = str(record["canonical"])
            if looks_like_alias_name(alias, canonical):
                false_positives.append(f"{alias}→{canonical} ({path.name})")

    assert false_positives == [], "启发式误合并金标 should_not_merge:\n" + "\n".join(false_positives)
