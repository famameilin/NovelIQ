from unittest.mock import MagicMock, patch

import pytest

from src.api.routes.results_fetchers import (
    _fetch_character_relations,
    _fetch_characters,
    _fetch_diagnosis,
    _fetch_hierarchical_relations,
    _normalize_arc_scores,
    _normalize_name_list,
    _normalize_text_by_alias_map,
)


class _DummyAnnotationRepo2:
    def __init__(self):
        self.session = object()
        self._pending = []

    def fetch_pending_chunk_relations(self, run_id, to_chunk=None, limit=200):
        return self._pending



class _DummyStatsRepo:
    def __init__(self, payload):
        self.payload = payload

    def fetch_cloud_analysis(self, novel_id, run_id):
        assert novel_id == "novel-1"
        assert run_id == "run-1"
        return self.payload


class _DummyAnnotationRepo:
    def __init__(self, alias_map, rows):
        self._alias_map = alias_map
        self._rows = rows

    def fetch_alias_map(self, run_id):
        assert run_id == "run-1"
        return self._alias_map

    def fetch_characters_with_scores(self, run_id):
        assert run_id == "run-1"
        return self._rows


def test_normalize_name_list_applies_alias_map_and_deduplicates():
    values = ["\u4e8c\u5988\u5988", "\u67f3\u5a49\u513f", "\u767d\u82b7"]
    alias_map = {"\u4e8c\u5988\u5988": "\u67f3\u5a49\u513f"}

    assert _normalize_name_list(values, alias_map) == ["\u67f3\u5a49\u513f", "\u767d\u82b7"]


def test_normalize_text_by_alias_map_rewrites_aliases_to_common_names():
    text = "\u7334\u5b50\u5e2e\u4e86\u4e8c\u5988\u5988\uff0c\u7b97\u76d8\u8fd8\u5728\u65c1\u8fb9\u770b\u7740\u4e8c\u5988\u5988\u3002"
    alias_map = {
        "\u7334\u5b50": "\u4faf\u98de\u767d",
        "\u7b97\u76d8": "\u6797\u7acb\u679c",
        "\u4e8c\u5988\u5988": "\u67f3\u5a49\u513f",
    }

    assert _normalize_text_by_alias_map(text, alias_map) == (
        "\u4faf\u98de\u767d\u5e2e\u4e86\u67f3\u5a49\u513f\uff0c"
        "\u6797\u7acb\u679c\u8fd8\u5728\u65c1\u8fb9\u770b\u7740\u67f3\u5a49\u513f\u3002"
    )


def test_normalize_text_by_alias_map_skips_embedded_suffixes_in_longer_names():
    text = "\u738b\u4f2f\u5b89\u770b\u89c1\u4e86\u4f2f\u5b89\uff0c\u4f46\u6ca1\u7406\u4f1a\u963f\u4f2f\u5b89\u3002"
    alias_map = {
        "\u4f2f\u5b89": "\u8d3a\u4f2f\u5b89",
    }

    assert _normalize_text_by_alias_map(text, alias_map) == (
        "\u738b\u4f2f\u5b89\u770b\u89c1\u4e86\u8d3a\u4f2f\u5b89\uff0c"
        "\u4f46\u6ca1\u7406\u4f1a\u963f\u4f2f\u5b89\u3002"
    )


def test_normalize_text_by_alias_map_skips_embedded_title_aliases():
    text = "\u6797\u5bb6\u5927\u5c11\u7237\u56de\u5e9c\uff0c\u8001\u795e\u4ed9\u63d0\u70b9\u4ed6\u795e\u4ed9\u6765\u4e86\u3002"
    alias_map = {
        "\u5927\u5c11\u7237": "\u8d3a\u4f2f\u5b89",
        "\u795e\u4ed9": "\u5f20\u9053\u9675",
    }

    assert _normalize_text_by_alias_map(text, alias_map) == (
        "\u6797\u5bb6\u5927\u5c11\u7237\u56de\u5e9c\uff0c"
        "\u8001\u795e\u4ed9\u63d0\u70b9\u4ed6\u5f20\u9053\u9675\u6765\u4e86\u3002"
    )


def test_normalize_text_by_alias_map_rewrites_standalone_title_aliases():
    text = "\u5927\u5c11\u7237\u56de\u5e9c\uff0c\u548c\u795e\u4ed9\u90fd\u6765\u4e86\u3002"
    alias_map = {
        "\u5927\u5c11\u7237": "\u8d3a\u4f2f\u5b89",
        "\u795e\u4ed9": "\u5f20\u9053\u9675",
    }

    assert _normalize_text_by_alias_map(text, alias_map) == (
        "\u8d3a\u4f2f\u5b89\u56de\u5e9c\uff0c\u548c\u5f20\u9053\u9675\u90fd\u6765\u4e86\u3002"
    )


def test_fetch_diagnosis_normalizes_all_character_name_fields():
    stats_repo = _DummyStatsRepo(
        {
            "foreshadow_rate": 0.3,
            "arc_scores": '{"\\u7334\\u5b50": 6.5, "\\u7b97\\u76d8": 6.0}',
            "narrative_type": "\u6210\u957f",
            "topic_labels": '["\\u4e8c\\u5988\\u5988", "\\u67f3\\u5a49\\u513f", "\\u767d\\u82b7"]',
            "diagnosis": "\u7334\u5b50\u5e2e\u52a9\u4e8c\u5988\u5988\uff0c\u7b97\u76d8\u968f\u540e\u51fa\u73b0\u3002",
            "value_logic_reason": "\u4e8c\u5988\u5988\u5f71\u54cd\u4e86\u7334\u5b50\u7684\u5224\u65ad\u3002",
            "power_stance_reason": "\u7b97\u76d8\u538b\u5236\u4e86\u4e8c\u5988\u5988\u3002",
            "dignity_reason": "\u4e8c\u5988\u5988\u4fdd\u6301\u4f53\u9762\u3002",
            "cultural_depth_reason": "\u7334\u5b50\u548c\u4e8c\u5988\u5988\u7684\u79f0\u547c\u5f88\u5e02\u4e95\u3002",
            "protagonist": "\u7334\u5b50",
            "main_characters": '["\\u7334\\u5b50", "\\u4e8c\\u5988\\u5988"]',
            "core_cast": '["\\u7334\\u5b50", "\\u7b97\\u76d8", "\\u4e8c\\u5988\\u5988"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
        alias_map={
            "\u7334\u5b50": "\u4faf\u98de\u767d",
            "\u7b97\u76d8": "\u6797\u7acb\u679c",
            "\u4e8c\u5988\u5988": "\u67f3\u5a49\u513f",
        },
    )

    assert result is not None
    assert result.arc_scores == {"\u4faf\u98de\u767d": 6.5, "\u6797\u7acb\u679c": 6.0}
    assert result.topic_labels == ["\u67f3\u5a49\u513f", "\u767d\u82b7"]
    assert result.diagnosis == "\u4faf\u98de\u767d\u5e2e\u52a9\u67f3\u5a49\u513f\uff0c\u6797\u7acb\u679c\u968f\u540e\u51fa\u73b0\u3002"
    assert result.value_logic_reason == "\u67f3\u5a49\u513f\u5f71\u54cd\u4e86\u4faf\u98de\u767d\u7684\u5224\u65ad\u3002"
    assert result.power_stance_reason == "\u6797\u7acb\u679c\u538b\u5236\u4e86\u67f3\u5a49\u513f\u3002"
    assert result.dignity_reason == "\u67f3\u5a49\u513f\u4fdd\u6301\u4f53\u9762\u3002"
    assert result.cultural_depth_reason == "\u4faf\u98de\u767d\u548c\u67f3\u5a49\u513f\u7684\u79f0\u547c\u5f88\u5e02\u4e95\u3002"
    assert result.protagonist == "\u4faf\u98de\u767d"
    assert result.main_characters == ["\u4faf\u98de\u767d", "\u67f3\u5a49\u513f"]
    assert result.core_cast == ["\u4faf\u98de\u767d", "\u6797\u7acb\u679c", "\u67f3\u5a49\u513f"]


def test_fetch_characters_marks_highest_fusion_score_as_protagonist():
    rows = []
    rows.extend([("\u7532", "\u5ba2\u4f53", "neutral")] * 20)
    rows.extend([("\u4e59", "\u4e3b\u4f53", "neutral")] * 10)

    annotation_repo = _DummyAnnotationRepo(alias_map={}, rows=rows)

    result = _fetch_characters(
        run_id="run-1",
        annotation_repo=annotation_repo,
        arc_scores={"\u7532": 1.0, "\u4e59": 10.0},
        main_characters=["\u4e59"],
    )

    protagonist = next(char for char in result if char.is_protagonist)
    support = next(char for char in result if char.name == "\u7532")

    assert protagonist.name == "\u4e59"
    assert protagonist.protagonist_score is not None
    assert support.protagonist_score is not None
    assert protagonist.protagonist_score > support.protagonist_score


def test_fetch_characters_returns_all_items_when_limit_is_none():
    rows = []
    rows.extend([("甲", "主体", "neutral")] * 3)
    rows.extend([("乙", "客体", "neutral")] * 2)
    rows.extend([("丙", "帮助者", "neutral")] * 1)

    annotation_repo = _DummyAnnotationRepo(alias_map={}, rows=rows)

    result = _fetch_characters(
        run_id="run-1",
        annotation_repo=annotation_repo,
        limit=None,
    )

    assert [char.name for char in result] == ["甲", "乙", "丙"]


def test_normalize_arc_scores_keeps_highest_score_when_aliases_collapse():
    arc_scores = {"monkey": 6.5, "hou_fei_bai": 8.0, "abacus": 4.0}
    alias_map = {
        "monkey": "hou_fei_bai",
        "abacus": "lin_li_guo",
    }

    assert _normalize_arc_scores(arc_scores, alias_map) == {
        "hou_fei_bai": 8.0,
        "lin_li_guo": 4.0,
    }


def test_fetch_character_relations_deduplicates_across_chunks():
    rows = [
        {"from_name": "贺伯安", "to_name": "二妈妈", "type": "家族", "last_seen_chunk": 3},
        {"from_name": "贺伯安", "to_name": "林立果", "type": "盟友", "last_seen_chunk": 5},
    ]

    annotation_repo = _DummyAnnotationRepo2()
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = rows

    with patch("src.api.routes.results_fetchers.fetchers.GraphRepository", return_value=mock_graph_repo):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
        )

    assert len(result) == 2

    rel1 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "二妈妈")
    assert rel1.chunk_id == 3
    assert rel1.type == "家族"
    assert rel1.change == "汇总"

    rel2 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "林立果")
    assert rel2.chunk_id == 5
    assert rel2.type == "盟友"



def test_fetch_character_relations_uses_last_seen_chunk_id():
    rows = [
        {"from_name": "张三", "to_name": "李四", "type": "朋友", "last_seen_chunk": 15},
    ]

    annotation_repo = _DummyAnnotationRepo2()
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = rows

    with patch("src.api.routes.results_fetchers.fetchers.GraphRepository", return_value=mock_graph_repo):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
        )

    assert len(result) == 1
    assert result[0].chunk_id == 15
    assert result[0].change == "汇总"


def test_fetch_character_relations_raises_when_pending_exists_and_graph_empty():
    annotation_repo = _DummyAnnotationRepo2()
    annotation_repo._pending = [object()]
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = []

    with patch("src.api.routes.results_fetchers.fetchers.GraphRepository", return_value=mock_graph_repo):
        with pytest.raises(RuntimeError, match="pending relations"):
            _fetch_character_relations(
                run_id="run-1",
                annotation_repo=annotation_repo,
            )


def test_fetch_character_relations_allows_empty_graph_when_no_pending():
    annotation_repo = _DummyAnnotationRepo2()
    annotation_repo._pending = []
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = []

    with patch("src.api.routes.results_fetchers.fetchers.GraphRepository", return_value=mock_graph_repo):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
        )

    assert result == []


def test_fetch_hierarchical_relations_normalizes_aliases_before_filtering():
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = [
        {
            "relation_id": 1,
            "type": "father_of",
            "from_name": "老贺",
            "to_name": "伯安",
            "first_seen_chunk": 2,
            "last_seen_chunk": 9,
        },
        {
            "relation_id": 2,
            "type": "ally_of",
            "from_name": "老贺",
            "to_name": "伯安",
            "first_seen_chunk": 2,
            "last_seen_chunk": 9,
        },
    ]

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        graph_repo=mock_graph_repo,
        alias_map={"老贺": "贺铮"},
        valid_character_names={"贺铮", "伯安"},
    )

    assert len(result) == 1
    assert result[0].from_entity == "贺铮"
    assert result[0].to_entity == "伯安"
    assert result[0].rel_type == "father_of"


def test_fetch_hierarchical_relations_filters_unknown_after_normalization():
    mock_graph_repo = MagicMock()
    mock_graph_repo.fetch_current_relations.return_value = [
        {
            "relation_id": 10,
            "type": "spouse_of",
            "from_name": "二妈妈",
            "to_name": "陌生人",
            "first_seen_chunk": 1,
            "last_seen_chunk": 4,
        }
    ]

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        graph_repo=mock_graph_repo,
        alias_map={"二妈妈": "柳婉儿"},
        valid_character_names={"柳婉儿", "贺伯安"},
    )

    assert result == []
