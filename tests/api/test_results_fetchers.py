from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.api.exceptions import GraphReadinessError
from src.api.routes.results_fetchers import (
    _fetch_character_relations,
    _fetch_characters,
    _fetch_chunk_annotations,
    _fetch_chunk_curves,
    _fetch_diagnosis,
    _fetch_foreshadowing_threads,
    _fetch_hierarchical_relations,
    _normalize_arc_scores,
    _normalize_name_list,
)
from src.knowledge.authority import ExportGraphAuthorityView, ExportRelationSnapshot, RelationEvent
from src.storage.repositories.annotation import ForeshadowingThreadView


class _DummyRow:
    """
    模拟 SQLAlchemy Row 对象，支持字段名访问

    修改时间: 2026-03-31
    任务: refactor-hardcoded-index-access
    修改内容: 新增类，用于测试中模拟 Row 对象
    """

    __slots__ = ("_fields", "_values")

    def __init__(self, **kwargs):
        object.__setattr__(self, "_fields", tuple(kwargs.keys()))
        object.__setattr__(self, "_values", tuple(kwargs.values()))

    def __getattr__(self, name):
        fields = object.__getattribute__(self, "_fields")
        values = object.__getattribute__(self, "_values")
        if name in fields:
            return values[fields.index(name)]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __getitem__(self, index):
        values = object.__getattribute__(self, "_values")
        return values[index]


class _DummyAnnotationRepo2:
    def __init__(self):
        self.session = object()


class _DummyStatsRepo:
    def __init__(self, payload):
        """
        修改时间: 2026-04-30
        任务: diagnosis-latest-only-reference-contract
        修改原因: 测试桩不再自动注入 reference_contract_version；所有 cloud_analysis 样例默认按最新结构读取。
        """
        self.payload = payload

    def fetch_cloud_analysis(self, novel_id, run_id):
        assert novel_id == "novel-1"
        assert run_id == "run-1"
        return self.payload


class _DummyCurveStatsRepo:
    def __init__(self, rows):
        self._rows = rows

    def fetch_chunk_curves_full(self, run_id):
        assert run_id == "run-1"
        return self._rows


class _DummyAnnotationRepo:
    def __init__(self, rows):
        self._rows = rows
        self.session = MagicMock()
        self.foreshadow_expectation = None

    def fetch_characters_with_scores(self, run_id):
        assert run_id == "run-1"
        return self._rows

    def fetch_chunk_annotations_full(self, run_id):
        assert run_id == "run-1"
        return []

    def fetch_chunk_dialogues_full(self, run_id):
        assert run_id == "run-1"
        return []

    def calculate_foreshadow_expectation(self, run_id):
        assert run_id == "run-1"
        return self.foreshadow_expectation

class _DummyChunkRepo:
    def __init__(self, style_rows):
        self._style_rows = style_rows

    def fetch_chunk_styles_full(self, run_id):
        assert run_id == "run-1"
        return self._style_rows


def test_normalize_name_list_deduplicates_graph_names():
    values = ["柳婉儿", "柳婉儿", "白芷"]

    assert _normalize_name_list(values) == ["柳婉儿", "白芷"]


def test_fetch_diagnosis_preserves_graph_resolved_character_fields():
    stats_repo = _DummyStatsRepo(
        {
            "foreshadow_expectation": 0.3,
            "arc_scores": '{"\\u4faf\\u98de\\u767d": 6.5, "\\u6797\\u7acb\\u679c": 6.0}',
            "genre_labels": '["\\u901a\\u7528"]',
            "style_labels": '["\\u4e25\\u8083"]',
            "topic_labels": '["\\u67f3\\u5a49\\u513f", "\\u67f3\\u5a49\\u513f", "\\u767d\\u82b7"]',
            "diagnosis": (
                "\u4faf\u98de\u767d\u5e2e\u52a9\u67f3\u5a49\u513f\uff0c"
                "\u6797\u7acb\u679c\u968f\u540e\u51fa\u73b0\u3002"
            ),
            "value_logic_reason": "\u67f3\u5a49\u513f\u5f71\u54cd\u4e86\u4faf\u98de\u767d\u7684\u5224\u65ad\u3002",
            "power_stance_reason": "\u6797\u7acb\u679c\u538b\u5236\u4e86\u67f3\u5a49\u513f\u3002",
            "dignity_reason": "\u67f3\u5a49\u513f\u4fdd\u6301\u4f53\u9762\u3002",
            "cultural_depth_reason": (
                "\u4faf\u98de\u767d\u548c\u67f3\u5a49\u513f"
                "\u7684\u79f0\u547c\u5f88\u5e02\u4e95\u3002"
            ),
            "focus_structure": "dual",
            "focus_characters": '["\\u4faf\\u98de\\u767d", "\\u6797\\u7acb\\u679c"]',
            "main_characters": '["\\u4faf\\u98de\\u767d", "\\u6797\\u7acb\\u679c"]',
            "core_cast": '["\\u4faf\\u98de\\u767d", "\\u6797\\u7acb\\u679c"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.arc_scores == {"\u4faf\u98de\u767d": 6.5, "\u6797\u7acb\u679c": 6.0}
    assert result.genre_labels == ["\u901a\u7528"]
    assert result.style_labels == ["\u4e25\u8083"]
    assert result.topic_labels == ["\u67f3\u5a49\u513f", "\u767d\u82b7"]
    assert result.diagnosis == (
        "\u4faf\u98de\u767d\u5e2e\u52a9\u67f3\u5a49\u513f\uff0c\u6797\u7acb\u679c\u968f\u540e\u51fa\u73b0\u3002"
    )
    assert result.value_logic_reason == "\u67f3\u5a49\u513f\u5f71\u54cd\u4e86\u4faf\u98de\u767d\u7684\u5224\u65ad\u3002"
    assert result.power_stance_reason == "\u6797\u7acb\u679c\u538b\u5236\u4e86\u67f3\u5a49\u513f\u3002"
    assert result.dignity_reason == "\u67f3\u5a49\u513f\u4fdd\u6301\u4f53\u9762\u3002"
    assert result.cultural_depth_reason == (
        "\u4faf\u98de\u767d\u548c\u67f3\u5a49\u513f\u7684\u79f0\u547c\u5f88\u5e02\u4e95\u3002"
    )
    assert result.focus_structure == "dual"
    assert result.focus_characters == ["\u4faf\u98de\u767d", "\u6797\u7acb\u679c"]
    assert result.main_characters == ["\u4faf\u98de\u767d", "\u6797\u7acb\u679c"]
    assert result.core_cast == ["\u4faf\u98de\u767d", "\u6797\u7acb\u679c"]
    assert result.foreshadow_expectation == 0.3


def test_fetch_foreshadowing_threads_preserves_confidence_field():
    class DummyRepo:
        def fetch_foreshadowing_threads(self, run_id):
            assert run_id == "run-1"
            return [
                ForeshadowingThreadView(
                    setup_id="setup-1",
                    first_chunk_id=2,
                    last_chunk_id=5,
                    anchor_chunk_ids=[2, 5],
                    setup_summary="黑伞只在雨夜自行张开",
                    setup_kind="异常物件",
                    expected_payoff_family="规则兑现",
                    payoff_likelihood="high",
                    confidence="medium",
                    strength="medium",
                    status="reinforced",
                    active=True,
                    latest_reason="具体钩子：黑伞在雨夜自行张开。未闭合原因：当前还没有解释它为何会自己张开。",
                    latest_why_unresolved_now="当前还没有解释它为何会自己张开。",
                )
            ]

    rows = _fetch_foreshadowing_threads("run-1", DummyRepo())

    assert len(rows) == 1
    assert rows[0].setup_id == "setup-1"
    assert rows[0].confidence == "medium"


def test_fetch_diagnosis_returns_none_when_cloud_diagnosis_missing():
    stats_repo = _DummyStatsRepo(None)

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "diagnosis_missing_focus_contract"


def test_fetch_diagnosis_uses_cloud_analysis_expectation_as_single_contract():
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: diagnosis 成功结果现在必须同时携带题材与风格标签；这里覆盖完整新合同的成功路径。
    """
    stats_repo = _DummyStatsRepo(
        {
            "foreshadow_expectation": 0.42,
            "arc_scores": '{"沈砚": 8.2}',
            "genre_labels": '["科幻"]',
            "style_labels": '["严肃"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.foreshadow_expectation == 0.42
    assert result.genre_labels == ["科幻"]
    assert result.style_labels == ["严肃"]
    assert result.focus_structure == "single"
    assert result.focus_characters == ["沈砚"]


def test_fetch_diagnosis_marks_focus_contract_incomplete_when_arc_scores_missing():
    stats_repo = _DummyStatsRepo(
        {
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_marks_focus_contract_incomplete_when_topic_labels_missing():
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"沈砚": 8.2}',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_marks_focus_contract_incomplete_when_genre_labels_missing():
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: 题材标签已经成为 diagnosis 正式合同，缺失时结果读取层必须显式要求 rerun。
    """
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"沈砚": 8.2}',
            "style_labels": '["严肃"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_marks_focus_contract_incomplete_when_style_labels_missing():
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: 风格标签和题材标签一样属于正式 diagnosis 合同，读取层不能再把缺风格标签的 row 当作成功结果。
    """
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"沈砚": 8.2}',
            "genre_labels": '["科幻"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_marks_focus_contract_incomplete_when_controlled_labels_invalid():
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: 读取层需要和 CloudAnalysisSchema 的受控标签合同一致；
          只要题材或风格标签不在允许集合内，就必须走 rerun-required。
    """
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"沈砚": 8.2}',
            "genre_labels": '["bad-genre"]',
            "style_labels": '["bad-style"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_normalizes_controlled_labels_before_returning():
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: 合法标签中的空白和重复值应在读取层被归一化，避免对外继续暴露脏数据。
    """
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"沈砚": 8.2}',
            "genre_labels": '[" 科幻 ", "科幻", " "]',
            "style_labels": '[" 严肃 ", "严肃"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is False
    assert result.genre_labels == ["科幻"]
    assert result.style_labels == ["严肃"]


def test_fetch_diagnosis_rejects_legacy_arc_score_list_contract():
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": "[8.2, 6.1]",
            "main_characters": '["沈砚", "陆明"]',
            "core_cast": '["沈砚", "陆明"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_returns_none_when_cloud_row_missing_focus_contract():
    stats_repo = _DummyStatsRepo(
        {
            "foreshadow_expectation": 0.42,
            "arc_scores": '{"沈砚": 8.2, "陆明": 7.4}',
            "main_characters": '["沈砚", "陆明"]',
            "core_cast": '["沈砚", "陆明"]',
            "diagnosis": "旧 diagnosis 行缺少 focus 字段",
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is True
    assert result.rerun_reason == "focus_contract_incomplete"


def test_fetch_diagnosis_accepts_missing_reference_contract_version_as_latest_shape():
    """
    修改时间: 2026-04-30
    任务: diagnosis-latest-only-reference-contract
    修改原因: latest-only 读侧不再把缺失的 reference_contract_version 当作旧合同分支；
              只要焦点合同字段完整，就应该按当前结构直接返回成功结果。
    """
    stats_repo = _DummyStatsRepo(
        {
            "foreshadow_expectation": 0.42,
            "arc_scores": '{"沈砚": 8.2}',
            "genre_labels": '["科幻"]',
            "style_labels": '["严肃"]',
            "topic_labels": '["成长"]',
            "focus_structure": "single",
            "focus_characters": '["沈砚"]',
            "main_characters": '["沈砚"]',
            "core_cast": '["沈砚"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.rerun_required is False
    assert result.rerun_reason is None
    assert result.foreshadow_expectation == 0.42
    assert result.focus_structure == "single"
    assert result.focus_characters == ["沈砚"]


def test_fetch_diagnosis_preserves_distinct_graph_entity_names():
    stats_repo = _DummyStatsRepo(
        {
            "arc_scores": '{"伯安": 7.2, "贺伯安": 8.3}',
            "genre_labels": '["通用"]',
            "style_labels": '["严肃"]',
            "topic_labels": '["成长"]',
            "focus_structure": "dual",
            "focus_characters": '["伯安", "贺伯安"]',
            "main_characters": '["伯安", "贺伯安"]',
            "core_cast": '["伯安", "贺伯安"]',
        }
    )

    result = _fetch_diagnosis(
        run_id="run-1",
        novel_id="novel-1",
        stats_repo=stats_repo,
    )

    assert result is not None
    assert result.arc_scores == {"伯安": 7.2, "贺伯安": 8.3}
    assert result.focus_structure == "dual"
    assert result.focus_characters == ["伯安", "贺伯安"]
    assert result.main_characters == ["伯安", "贺伯安"]
    assert result.core_cast == ["伯安", "贺伯安"]


def test_fetch_characters_marks_focus_characters_and_keeps_center_scores():
    rows = []
    rows.extend([_DummyRow(name="\u7532", role_function="\u5ba2\u4f53", emotion_score="neutral")] * 20)
    rows.extend([_DummyRow(name="\u4e59", role_function="\u4e3b\u4f53", emotion_score="neutral")] * 10)

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    result = _fetch_characters(
        run_id="run-1",
        annotation_repo=annotation_repo,
        arc_scores={"\u7532": 1.0, "\u4e59": 10.0},
        focus_characters=["\u4e59", "\u7532"],
        main_characters=["\u4e59"],
    )

    focus_character_names = {char.name for char in result if char.is_focus_character}
    support = next(char for char in result if char.name == "\u7532")
    focal = next(char for char in result if char.name == "\u4e59")

    assert focus_character_names == {"\u4e59", "\u7532"}
    assert focal.narrative_focus_score is not None
    assert support.narrative_focus_score is not None
    assert focal.narrative_focus_score > support.narrative_focus_score


def test_fetch_characters_returns_all_items_when_limit_is_none():
    rows = []
    rows.extend([_DummyRow(name="甲", role_function="主体", emotion_score="neutral")] * 3)
    rows.extend([_DummyRow(name="乙", role_function="客体", emotion_score="neutral")] * 2)
    rows.extend([_DummyRow(name="丙", role_function="帮助者", emotion_score="neutral")] * 1)

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    result = _fetch_characters(
        run_id="run-1",
        annotation_repo=annotation_repo,
        limit=None,
    )

    assert [char.name for char in result] == ["甲", "乙", "丙"]


def test_fetch_characters_filters_unresolved_pronoun_references():
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    说明: 角色榜只展示 global-character 准入后的名字，未解析“我”不能进入聚合结果。
    """
    rows = [
        _DummyRow(name="我", role_function="主体", emotion_score="neutral"),
        _DummyRow(name="沈砚", role_function="主体", emotion_score="neutral"),
    ]

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    result = _fetch_characters(
        run_id="run-1",
        annotation_repo=annotation_repo,
        limit=None,
    )

    assert [char.name for char in result] == ["沈砚"]


def test_normalize_arc_scores_preserves_named_scores():
    arc_scores = {"monkey": 6.5, "hou_fei_bai": 8.0, "abacus": 4.0}

    assert _normalize_arc_scores(arc_scores) == {
        "monkey": 6.5,
        "hou_fei_bai": 8.0,
        "abacus": 4.0,
    }


def test_normalize_arc_scores_returns_none_when_payload_is_not_named_mapping():
    assert _normalize_arc_scores([8.0, 6.0]) is None


def test_fetch_character_relations_deduplicates_across_chunks():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(from_name="贺伯安", to_name="二妈妈", relation_type="家族", last_seen_chunk=3),
            ExportRelationSnapshot(from_name="贺伯安", to_name="林立果", relation_type="盟友", last_seen_chunk=5),
        ]
    )

    with patch(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert len(result) == 2

    rel1 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "二妈妈")
    assert rel1.chunk_id == 3
    assert rel1.type == "家族"
    assert rel1.change == "汇总"

    rel2 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "林立果")
    assert rel2.chunk_id == 5
    assert rel2.type == "盟友"


def test_fetch_character_relations_skips_inactive_current_relations():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                from_name="贺伯安",
                to_name="二妈妈",
                relation_type="家族",
                last_seen_chunk=3,
                is_active=False,
            ),
            ExportRelationSnapshot(
                from_name="贺伯安",
                to_name="林立果",
                relation_type="盟友",
                last_seen_chunk=5,
                is_active=True,
            ),
        ]
    )

    with patch(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert [(item.from_char, item.to_char) for item in result] == [("贺伯安", "林立果")]


def test_fetch_chunk_curves_adds_surface_tension_without_rewriting_raw_proxy():
    stats_repo = _DummyCurveStatsRepo(
        [
            _DummyRow(
                chunk_id=1,
                pos_density=0.0,
                neg_density=0.0,
                net_density=0.0,
                smoothed_density=0.0,
                tension_proxy=0.9,
                tension_composite=0.2,
            ),
            _DummyRow(
                chunk_id=2,
                pos_density=0.0,
                neg_density=0.0,
                net_density=0.0,
                smoothed_density=0.0,
                tension_proxy=0.1,
                tension_composite=0.7,
            ),
        ]
    )
    annotation_repo = _DummyAnnotationRepo(rows=[])
    chunk_repo = _DummyChunkRepo(
        [
            _DummyRow(
                chunk_id=1,
                fight_density=0.0,
                exclaim_density=0.0,
                question_density=0.0,
                dialogue_ratio=0.0,
                sent_len_std=0.0,
                sensory_density=0.0,
            ),
            _DummyRow(
                chunk_id=2,
                fight_density=0.6,
                exclaim_density=0.2,
                question_density=0.2,
                dialogue_ratio=0.5,
                sent_len_std=0.4,
                sensory_density=0.3,
            ),
        ]
    )

    result = _fetch_chunk_curves(
        run_id="run-1",
        stats_repo=stats_repo,
        annotation_repo=annotation_repo,
        chunk_repo=chunk_repo,
    )

    assert len(result) == 2
    assert result[0].tension_proxy == 0.9
    assert result[1].tension_proxy == 0.1
    assert result[0].surface_tension is not None
    assert result[1].surface_tension is not None
    assert result[1].surface_tension > result[0].surface_tension


def test_fetch_character_relations_uses_last_seen_chunk_id():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(from_name="张三", to_name="李四", relation_type="朋友", last_seen_chunk=15),
        ]
    )

    with patch(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert len(result) == 1
    assert result[0].chunk_id == 15
    assert result[0].change == "汇总"


def test_fetch_character_relations_raises_when_pending_exists_and_graph_empty():
    annotation_repo = _DummyAnnotationRepo2()
    with patch(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(
            assert_graph_ready=lambda _run_id: (_ for _ in ()).throw(
                GraphReadinessError(
                    "database graph is still pending; finish graph persistence before reading authority views."
                )
            )
        ),
    ):
        with pytest.raises(GraphReadinessError, match="database graph is still pending"):
            _fetch_character_relations(
                run_id="run-1",
                annotation_repo=annotation_repo,
                export_graph_view=ExportGraphAuthorityView(),
            )


def test_fetch_character_relations_allows_empty_graph_when_no_pending():
    annotation_repo = _DummyAnnotationRepo2()
    with patch(
        "src.api.routes.results_fetchers.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=ExportGraphAuthorityView(),
        )

    assert result == []


def test_fetch_hierarchical_relations_uses_graph_entity_names():
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=1,
                from_name="贺铮",
                to_name="伯安",
                relation_type="father_of",
                first_seen_chunk=2,
                last_seen_chunk=9,
            ),
            ExportRelationSnapshot(
                relation_id=2,
                from_name="贺铮",
                to_name="伯安",
                relation_type="ally_of",
                first_seen_chunk=2,
                last_seen_chunk=9,
            ),
        ]
    )

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        export_graph_view=export_graph_view,
        valid_character_names={"贺铮", "伯安"},
    )

    assert len(result) == 1
    assert result[0].from_entity == "贺铮"
    assert result[0].to_entity == "伯安"
    assert result[0].rel_type == "father_of"


def test_fetch_hierarchical_relations_filters_unknown_graph_endpoint():
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=10,
                from_name="柳婉儿",
                to_name="陌生人",
                relation_type="spouse_of",
                first_seen_chunk=1,
                last_seen_chunk=4,
            )
        ]
    )

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        export_graph_view=export_graph_view,
        valid_character_names={"柳婉儿", "贺伯安"},
    )

    assert result == []


def test_fetch_hierarchical_relations_skips_inactive_current_relations():
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=1,
                from_name="老贺",
                to_name="伯安",
                relation_type="father_of",
                first_seen_chunk=2,
                last_seen_chunk=9,
                is_active=False,
            ),
            ExportRelationSnapshot(
                relation_id=2,
                from_name="老贺",
                to_name="阿明",
                relation_type="father_of",
                first_seen_chunk=3,
                last_seen_chunk=10,
                is_active=True,
            ),
        ]
    )

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        export_graph_view=export_graph_view,
        valid_character_names={"老贺", "伯安", "阿明"},
    )

    assert [(item.rel_id, item.from_entity, item.to_entity) for item in result] == [(2, "老贺", "阿明")]


def test_fetch_hierarchical_relations_keeps_supported_non_character_hierarchy():
    export_graph_view = ExportGraphAuthorityView(
        canonical_entities=[
            SimpleNamespace(name="伯安", entity_type="character"),
            SimpleNamespace(name="贺家", entity_type="organization"),
            SimpleNamespace(name="赵甲卫", entity_type="group"),
        ],
        current_relations=[
            ExportRelationSnapshot(
                relation_id=11,
                from_name="伯安",
                to_name="贺家",
                relation_type="belongs_to",
                first_seen_chunk=2,
                last_seen_chunk=9,
                is_active=True,
            ),
            ExportRelationSnapshot(
                relation_id=12,
                from_name="赵甲卫",
                to_name="贺家",
                relation_type="affiliated_with",
                first_seen_chunk=3,
                last_seen_chunk=10,
                is_active=True,
            ),
        ],
    )

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        export_graph_view=export_graph_view,
        valid_character_names={"伯安"},
    )

    assert [(item.rel_id, item.rel_type, item.from_entity, item.to_entity) for item in result] == [
        (11, "belongs_to", "伯安", "贺家"),
        (12, "affiliated_with", "赵甲卫", "贺家"),
    ]


def test_fetch_chunk_annotations_builds_relations_from_export_authority_view():
    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chunk_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chunk_id=3,
                    emotional_valence="正向",
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=False,
                    is_strong_setup=False,
                    foreshadowing_type=None,
                    setup_kind=None,
                    foreshadowing_desc=None,
                    why_unresolved_now=None,
                    expected_payoff_family=None,
                )
            ]

        def fetch_chunk_characters_full(self, _run_id):
            return []

        def fetch_chunk_dialogues_full(self, _run_id):
            return []

    annotation_repo = _AnnotationRepoWithChunkRows()
    export_graph_view = ExportGraphAuthorityView(
        relation_events=[
            RelationEvent(
                relation_event_id=101,
                chunk_id=3,
                from_entity_id=1,
                to_entity_id=2,
                from_name="贺铮",
                to_name="伯安",
                relation_type="父子",
                change_type="新建",
            )
        ]
    )

    result = _fetch_chunk_annotations(
        run_id="run-1",
        annotation_repo=annotation_repo,
        valid_character_names={"贺铮", "伯安"},
        export_graph_view=export_graph_view,
    )

    assert len(result) == 1
    assert result[0].is_strong_setup is False
    assert result[0].setup_kind is None
    assert result[0].why_unresolved_now is None
    assert result[0].expected_payoff_family is None
    assert len(result[0].relations) == 1
    assert result[0].relations[0].from_char == "贺铮"
    assert result[0].relations[0].to_char == "伯安"
    assert result[0].relations[0].type == "父子"
    assert result[0].relations[0].change == "新建"


def test_fetch_chunk_annotations_uses_explicit_database_graph_view():
    """2026-08-05 用于验证 chunk 展开结果只读取显式数据库图视图"""
    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chunk_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chunk_id=3,
                    emotional_valence="正向",
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=True,
                    is_strong_setup=True,
                    foreshadowing_type="物件",
                    setup_kind="异常物件",
                    foreshadowing_desc=(
                        "玉佩发热 - 具体钩子：玉佩出现异常发热。"
                        "未闭合原因：当前还没有解释它为何会发热。"
                    ),
                    why_unresolved_now="当前还没有解释它为何会发热。",
                    expected_payoff_family="能力触发",
                )
            ]

        def fetch_chunk_characters_full(self, _run_id):
            return []

        def fetch_chunk_dialogues_full(self, _run_id):
            return []

    result = _fetch_chunk_annotations(
        run_id="run-1",
        annotation_repo=_AnnotationRepoWithChunkRows(),
        export_graph_view=ExportGraphAuthorityView(),
    )

    assert len(result) == 1
    assert result[0].chunk_id == 3
    assert result[0].is_strong_setup is True
    assert result[0].setup_kind == "异常物件"
    assert result[0].relations == []


def test_fetch_chunk_annotations_propagates_database_graph_failure(monkeypatch):
    """2026-08-05 用于验证 chunk 消费者不会在数据库图失败时降级读取"""
    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chunk_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chunk_id=3,
                    emotional_valence="正向",
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=False,
                    is_strong_setup=False,
                    foreshadowing_type=None,
                    setup_kind=None,
                    foreshadowing_desc=None,
                    why_unresolved_now=None,
                    expected_payoff_family=None,
                )
            ]

        def fetch_chunk_characters_full(self, _run_id):
            return []

        def fetch_chunk_dialogues_full(self, _run_id):
            return []

    annotation_repo = _AnnotationRepoWithChunkRows()

    class _GraphUnavailableService:
        def build_export_view(self, _run_id):
            raise GraphReadinessError("graph participant state is stale or incomplete")

    monkeypatch.setattr(
        "src.api.services.results_queries.chunks.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: _GraphUnavailableService(),
    )

    with pytest.raises(GraphReadinessError, match="graph participant state is stale"):
        _fetch_chunk_annotations(
            run_id="run-1",
            annotation_repo=annotation_repo,
        )
