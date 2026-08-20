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
        chapter_id=3,
        chapter_order=3,
        fact_id="fact-12",
        effective_chapter_id=12,
        changes=[{"change_kind": "新建", "field": "relation_type"}],
        entity_id=None,
        entity_name=None,
        relation_id="relation-7",
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
    assert change.effective_chapter_id == 12
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


def test_graph_changes_page_clamps_limit_and_passes_offset() -> None:
    """2026-08-13 补测试 P1：fetch_changes 的 limit 钳制（1~200）与 cursor→offset 传递
    此前只有前端 hook 测试（MSW mock），后端路由参数从未被断言。"""
    row = SimpleNamespace(
        change_id="relation:12:4",
        change_kind="relation",
        chapter_id=3,
        chapter_order=3,
        fact_id="fact-12",
        effective_chapter_id=12,
        changes=[{"change_kind": "新建", "field": "relation_type"}],
        entity_id=None,
        entity_name=None,
        relation_id="relation-7",
        from_entity_id=1,
        to_entity_id=2,
        from_name="顾霜",
        to_name="司夜",
        relation_type="盟友",
        directionality="bidirectional",
        relation_semantics="ordinary",
    )
    annotation_repo = SimpleNamespace(session=object())

    # 超上限的 changes_limit 必须被钳制到 200
    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_changes.return_value = ([row], 1)
        _fetch_graph_changes_page("run-1", annotation_repo, changes_limit=500)
        graph_repository.return_value.fetch_changes.assert_called_once_with(
            "run-1", chapter_id=None, offset=0, limit=200
        )

    # cursor 解码出的 offset 必须透传给 fetch_changes
    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_changes.return_value = ([row], 10)
        cursor = _encode_graph_changes_cursor(5)
        _fetch_graph_changes_page("run-1", annotation_repo, changes_cursor=cursor, changes_limit=2)
        graph_repository.return_value.fetch_changes.assert_called_once_with(
            "run-1", chapter_id=None, offset=5, limit=2
        )

    # 下限钳制：changes_limit=0 → 1
    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_changes.return_value = ([row], 1)
        _fetch_graph_changes_page("run-1", annotation_repo, changes_limit=0)
        graph_repository.return_value.fetch_changes.assert_called_once_with(
            "run-1", chapter_id=None, offset=0, limit=1
        )


def test_graph_changes_page_rejects_out_of_range_cursor() -> None:
    """2026-08-13 补测试 P1：游标偏移越过 total 时必须抛 ValueError（路由层 →400），
    不得返回空页冒充合法分页。"""
    row = SimpleNamespace(
        change_id="relation:1:1",
        change_kind="relation",
        chapter_id=1,
        chapter_order=1,
        fact_id="f",
        effective_chapter_id=1,
        changes=[{"change_kind": "新建", "field": "relation_type"}],
        entity_id=None,
        entity_name=None,
        relation_id="r",
        from_entity_id=1,
        to_entity_id=2,
        from_name="A",
        to_name="B",
        relation_type="盟友",
        directionality="bidirectional",
        relation_semantics="ordinary",
    )
    annotation_repo = SimpleNamespace(session=object())
    with patch("src.api.services.results_queries.graph.GraphRepository") as graph_repository:
        graph_repository.return_value.fetch_changes.return_value = ([row], 1)
        with pytest.raises(ValueError, match="out of range"):
            _fetch_graph_changes_page(
                "run-1",
                annotation_repo,
                changes_cursor=_encode_graph_changes_cursor(10),
            )
