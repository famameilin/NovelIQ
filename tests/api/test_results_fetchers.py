from src.api.routes.results_fetchers import (
    _fetch_characters,
    _fetch_diagnosis,
    _normalize_name_list,
    _normalize_text_by_alias_map,
)


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
