"""按段落证据把语义命中映射到事件、事件树与参与者"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def event_paragraph_ids(item: Mapping[str, Any]) -> list[int]:
    """事件记录上的全部证据段落身份；兼容单段字段与证据数组两种形态"""
    values: list[int] = []
    content = item.get("content")
    source = content if isinstance(content, Mapping) else item
    single = source.get("evidence_paragraph_id")
    if isinstance(single, int) and not isinstance(single, bool):
        values.append(single)
    for row in source.get("evidence") or []:
        if isinstance(row, Mapping):
            paragraph_id = row.get("paragraph_id")
            if isinstance(paragraph_id, int) and not isinstance(paragraph_id, bool):
                values.append(paragraph_id)
    return values


def paragraph_ranks(paragraph_ids: Sequence[int]) -> dict[int, int]:
    """语义命中段落的排序权重：越靠前相似度越高"""
    return {int(paragraph_id): rank for rank, paragraph_id in enumerate(paragraph_ids)}


def best_paragraph_rank(item: Mapping[str, Any], ranks: Mapping[int, int]) -> int | None:
    """条目在语义命中段落上的最好名次；没有命中返回 None"""
    hits = [ranks[value] for value in event_paragraph_ids(item) if value in ranks]
    return min(hits) if hits else None


def ranked_keys(
    items: Iterable[Mapping[str, Any]],
    ranks: Mapping[int, int],
    key_of,
) -> list[str]:
    """按语义命中段落把条目归到稳定身份上，身份按命中段落的最好名次排序"""
    best: dict[str, int] = {}
    for item in items:
        rank = best_paragraph_rank(item, ranks)
        if rank is None:
            continue
        identifier = key_of(item)
        if not identifier:
            continue
        if identifier not in best or rank < best[identifier]:
            best[identifier] = rank
    return [identifier for identifier, _ in sorted(best.items(), key=lambda pair: (pair[1], pair[0]))]


__all__ = [
    "best_paragraph_rank",
    "event_paragraph_ids",
    "paragraph_ranks",
    "ranked_keys",
]
