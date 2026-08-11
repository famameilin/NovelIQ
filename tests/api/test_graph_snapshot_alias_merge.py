"""章节图快照消歧合并测试"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.api.models.graph import GraphSnapshotResponse
from src.api.services.results_queries.graph import _fetch_graph_snapshot


def _entity(entity_id: int, name: str) -> SimpleNamespace:
    """2026-08-09 用于构造实体快照桩"""
    return SimpleNamespace(
        entity_id=entity_id,
        name=name,
        entity_type="character",
        tags=[],
        first_seen_chunk=0,
        last_seen_chunk=3,
        state_revision=1,
        state={"status": "active"},
    )


def _relation(
    *,
    relation_id: str,
    from_entity_id: int,
    to_entity_id: int,
    from_name: str,
    to_name: str,
    relation_type: str = "友情",
    relation_semantics: str = "ordinary",
    attributes: dict | None = None,
) -> SimpleNamespace:
    """2026-08-09 用于构造关系快照桩"""
    return SimpleNamespace(
        relation_id=relation_id,
        relation_version_id=1,
        relation_revision=1,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        from_name=from_name,
        to_name=to_name,
        relation_type=relation_type,
        directionality="bidirectional",
        relation_semantics=relation_semantics,
        attributes=attributes or {},
        is_active=True,
        changes=[],
    )


def test_graph_snapshot_merges_alias_nodes_and_rewrites_edges() -> None:
    """2026-08-09 用于验证图谱快照折叠别名节点并重写边端点"""
    version = SimpleNamespace(
        graph_version_id="graph-version-9",
        chapter_id=9,
        chapter_order=9,
        first_chunk_id=8,
        last_chunk_id=8,
    )
    snapshot = SimpleNamespace(
        graph_version=version,
        entities=[
            _entity(67, "伯安"),
            _entity(97, "贺重明"),
            _entity(38, "贺伯安"),
        ],
        relations=[
            _relation(
                relation_id="r-1",
                from_entity_id=67,
                to_entity_id=97,
                from_name="伯安",
                to_name="贺重明",
                relation_type="同一人物",
                relation_semantics="same_character",
                attributes={"representative_entity_id": 67},
            ),
            _relation(
                relation_id="r-2",
                from_entity_id=67,
                to_entity_id=38,
                from_name="伯安",
                to_name="贺伯安",
            ),
        ],
    )
    annotation_repo = SimpleNamespace(session=object())

    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_snapshot.return_value = snapshot

        payload = _fetch_graph_snapshot("run-1", annotation_repo)

    response = GraphSnapshotResponse.model_validate(payload)
    node_names = {node.name for node in response.nodes}
    assert node_names == {"伯安", "贺伯安"}
    boan = next(node for node in response.nodes if node.name == "伯安")
    assert boan.aliases == ["贺重明"]
    assert all(edge.relation_semantics != "same_character" for edge in response.edges)
    assert [(edge.source_name, edge.target_name) for edge in response.edges] == [
        ("伯安", "贺伯安")
    ]
