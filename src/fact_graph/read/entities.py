"""事实图的人物可见性裁决，仓储只返回实际快照"""

from __future__ import annotations

from src.fact_graph.character_reference_policy import is_global_character_surface_name
from src.storage.contracts.stores import GraphStore
from src.storage.records.graph import EntitySnapshotRow


def fetch_latest_entities(
    repository: GraphStore, run_id: str, *, entity_type: str | None = None
) -> list[EntitySnapshotRow]:
    return [
        row
        for row in repository.fetch_latest_entity_rows(run_id, entity_type=entity_type)
        if row.entity_type != "character" or is_global_character_surface_name(row.name)
    ]
