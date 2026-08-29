"""语言特征 tab 组装（实体与短语）"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.api.services.results_queries.linguistic import (
    aggregate_phrase_stats,
    fetch_entity_candidates,
)

_SURFACE_TOP_LIMIT = 20


def build_linguistic_entities_tab(run_id: str, session: Session) -> dict[str, Any]:
    """
    实体与短语 tab：实体类型计数 + 高频实体名 + 固定短语统计

    只回聚合统计，不透出实体候选 span 明细（底层原始行）；高频实体名按
    surface_text + 归一类型 group-by 计数取 Top-N（确定性排序，平序按字典序）。
    """
    entities_data = fetch_entity_candidates(run_id, session)
    phrase_stats = aggregate_phrase_stats(run_id, session)

    counter: dict[tuple[str, str], int] = {}
    for entity in entities_data["entities"]:
        key = (entity["surface_text"], entity["normalized_entity_type"] or "unmapped")
        counter[key] = counter.get(key, 0) + 1
    surface_top = [
        {"surface_text": surface, "entity_type": entity_type, "count": count}
        for (surface, entity_type), count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ][: _SURFACE_TOP_LIMIT]

    return {
        "run_id": run_id,
        "count_by_type": entities_data["count_by_type"],
        "surface_top": surface_top,
        "total_char_count": phrase_stats["total_char_count"],
        "metric_hit_count": phrase_stats["metric_hit_count"],
        "fixed_phrase_density": phrase_stats["fixed_phrase_density"],
        "four_char_candidate_count": phrase_stats["four_char_candidate_count"],
        "total_hits": phrase_stats["total_hits"],
        "unavailable_reason": entities_data["unavailable_reason"],
    }
