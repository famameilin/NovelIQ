"""章节图变化接口展示字段测试"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.api.models.graph import GraphChangesResponse
from src.api.services.results_queries.graph import (
    _decode_graph_changes_cursor,
    _encode_graph_changes_cursor,
    _fetch_graph_changes_page,
)


def test_graph_changes_page_exposes_typed_presentation_fields() -> None:
    """2026-08-07 用于验证图变化分页直接返回页面展示与定位字段"""
    row = SimpleNamespace(
        change_id="relation:12:4",
        change_kind="relation",
        graph_version_id="graph-version-12",
        chapter_id=3,
        chapter_order=3,
        fact_id="fact-12",
        fact_revision=4,
        effective_chunk_id=12,
        changes=[{"change_kind": "新建", "field": "relation_type"}],
        entity_id=None,
        entity_name=None,
        relation_id="relation-7",
        relation_version_id=17,
        relation_revision=4,
        from_entity_id=1,
        to_entity_id=2,
        from_name="顾霜",
        to_name="司夜",
        relation_type="盟友",
        directionality="bidirectional",
        relation_semantics="ordinary",
    )
    annotation_repo = SimpleNamespace(session=object())

    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_changes.return_value = ([row], 1)

        payload = _fetch_graph_changes_page("run-1", annotation_repo, changes_limit=20)

    response = GraphChangesResponse.model_validate(payload)
    change = response.changes[0]
    assert change.effective_chunk_id == 12
    assert change.relation_id == "relation-7"
    assert change.from_entity_id == 1
    assert change.to_entity_id == 2
    assert change.from_name == "顾霜"
    assert change.to_name == "司夜"
    assert change.relation_change_kind == "新建"
    assert change.directionality == "bidirectional"


def test_graph_changes_cursor_round_trip() -> None:
    """2026-08-12 用于验证合法游标可往返解析"""
    assert _decode_graph_changes_cursor(_encode_graph_changes_cursor(12)) == 12
    assert _decode_graph_changes_cursor(None) == 0
    assert _decode_graph_changes_cursor("") == 0


@pytest.mark.parametrize("raw_payload", ["[1, 2, 3]", '"not-a-dict"', "42", "null"])
def test_graph_changes_cursor_rejects_non_dict_payload(raw_payload: str) -> None:
    """2026-08-12 用于验证非 dict JSON 载荷按非法游标处理（→400）而非 AttributeError（→500）"""
    encoded = urlsafe_b64encode(raw_payload.encode("utf-8")).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="invalid graph changes cursor"):
        _decode_graph_changes_cursor(encoded)
