from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.diagnosis.persistence import save_diagnosis_report
from src.api.exceptions import GraphReadinessError
from src.api.services.results_queries import _fetch_character_relations, _fetch_diagnosis, _fetch_hierarchical_relations
from src.diagnosis.normalization import normalize_arc_scores, normalize_name_list
from src.diagnosis.schema import AgentAnalysis
from src.event_trees.organization import register_diagnosis_session
from src.fact_graph.read import ExportGraphAuthorityView, ExportRelationSnapshot, GraphChange
from src.metrics.queries.global_stats import save_global_stats
from src.storage.repositories import StatsRepository
from src.storage.repositories.annotation import ForeshadowingTreeView
from tests.support.chapter_annotation_helpers import create_run_with_chunks
from tests.support.event_tree_fixtures import ensure_character
from tests.support.paragraph_fixtures import insert_metrics, make_metric_row
from tests.support.results_query_stubs import _fetch_chapter_annotations, _fetch_characters, _fetch_foreshadowing_trees


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


def _publish_diagnosis(
    db_session,
    run_id: str,
    *,
    register_names: bool = True,
    **fields: object,
) -> str:
    """正式发布链写入一份诊断报告：标签/名单/评分随报告落库

    名单与评分引用的角色必须先是本 run 的正式 character 实体；报告正文与
    评分形状由 AgentAnalysis 收口，测试不再手拼读取载荷。
    """
    names = {
        *dict(fields.get("arc_scores") or {}),
        *list(fields.get("focus_characters") or []),
        *list(fields.get("main_characters") or []),
        *list(fields.get("core_cast") or []),
    }
    if register_names:
        for name in sorted(str(item) for item in names):
            ensure_character(db_session, run_id=run_id, name=name)
    session_id = f"diag-session-{uuid4().hex[:12]}"
    register_diagnosis_session(db_session, run_id=run_id, session_id=session_id)
    report_id = save_diagnosis_report(db_session, run_id, session_id, AgentAnalysis(**fields))
    db_session.commit()
    return report_id


def _diagnosis_scenario(db_session, **fields: object) -> tuple[str, str]:
    """一段正文 + 一份正式诊断报告的读取场景，返回 (novel_id, run_id)"""
    novel_id, run_id = create_run_with_chunks(db_session, texts=["伯安帮了柳婉儿。"], title="诊断读取测试")
    _publish_diagnosis(db_session, run_id, **fields)
    return novel_id, run_id


def _diagnosis_result(db_session, novel_id: str, run_id: str):
    """按生产读入口读取诊断：运行统计走正式仓储，不注入假载荷"""
    return _fetch_diagnosis(run_id=run_id, novel_id=novel_id, stats_repo=StatsRepository(db_session))


def test_fetch_diagnosis_preserves_topic_ids_and_precise_emotion_context(db_session) -> None:
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        topic_labels={"8": "家门与师门", "0": "学堂日常"},
    )
    # 情绪上下文来自本运行的正式充分统计量（分子/分母守恒密度）
    insert_metrics(db_session, run_id, [make_metric_row(0, token_count=2, positive_weight_sum=1.0)])
    save_global_stats(db_session, run_id)

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    # 主题命名按实际 topic_id 键控透传
    assert result.topic_labels == {"8": "家门与师门", "0": "学堂日常"}
    assert result.emotion_avg == pytest.approx(0.5)
    assert result.lexicon_zero_hit_share == pytest.approx(0.0)


class _DummyAnnotationRepo:
    def __init__(self, rows):
        self._rows = rows
        self.session = MagicMock()
        self.foreshadow_expectation = None

    def fetch_chapter_characters_full(self, run_id):
        assert run_id == "run-1"
        return self._rows

    def fetch_chapter_annotations_full(self, run_id):
        assert run_id == "run-1"
        return []

    def fetch_chapter_dialogues_full(self, run_id):
        assert run_id == "run-1"
        return []

    def calculate_foreshadow_expectation(self, run_id):
        assert run_id == "run-1"
        return self.foreshadow_expectation


def test_normalize_name_list_deduplicates_graph_names():
    values = ["柳婉儿", "柳婉儿", "白芷"]

    assert normalize_name_list(values) == ["柳婉儿", "白芷"]


def test_fetch_diagnosis_preserves_graph_resolved_character_fields(db_session) -> None:
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"侯飞白": 6.5, "林立果": 6.0},
        genre_labels=["通用"],
        style_labels=["严肃"],
        diagnosis="侯飞白帮助柳婉儿，林立果随后出现。",
        value_logic_reason="柳婉儿影响了侯飞白的判断。",
        power_stance_reason="林立果压制了柳婉儿。",
        dignity_reason="柳婉儿保持体面。",
        cultural_depth_reason="侯飞白和柳婉儿的称呼很市井。",
        focus_structure="dual",
        focus_characters=["侯飞白", "林立果"],
        main_characters=["侯飞白", "林立果"],
        core_cast=["侯飞白", "林立果"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.arc_scores == {"侯飞白": 6.5, "林立果": 6.0}
    assert result.genre_labels == ["通用"]
    assert result.style_labels == ["严肃"]
    # 历史主题标签数组形态已无法经正式写面产生（写面只收 topic_id→标签映射）
    assert not result.topic_labels
    assert result.diagnosis == "侯飞白帮助柳婉儿，林立果随后出现。"
    assert result.value_logic_reason == "柳婉儿影响了侯飞白的判断。"
    assert result.power_stance_reason == "林立果压制了柳婉儿。"
    assert result.dignity_reason == "柳婉儿保持体面。"
    assert result.cultural_depth_reason == "侯飞白和柳婉儿的称呼很市井。"
    assert result.focus_structure == "dual"
    assert result.focus_characters == ["侯飞白", "林立果"]
    assert result.main_characters == ["侯飞白", "林立果"]
    assert result.core_cast == ["侯飞白", "林立果"]
    # 伏笔预期是正式伏笔链的读投影：本例没有伏笔链，不冒充旧 payload 的存储值
    assert result.foreshadow_expectation is None


def test_fetch_foreshadowing_trees_preserves_status_field():
    """2026-09-13 伏笔树视图经 fetchers 透传（伏笔即事件树）"""

    class DummyRepo:
        def fetch_foreshadowing_trees(self, run_id):
            assert run_id == "run-1"
            return [
                ForeshadowingTreeView(
                    root_event_id="evt-root-1",
                    tree_id="tree-1",
                    first_chapter_id=2,
                    last_chapter_id=5,
                    anchor_chapter_ids=[2, 5],
                    description="黑伞只在雨夜自行张开",
                    payoff_likelihood="high",
                    strength="medium",
                    status="reinforced",
                    active=True,
                    latest_reason="具体钩子：黑伞在雨夜自行张开。未闭合原因：当前还没有解释它为何会自己张开。",
                    latest_why_unresolved_now="当前还没有解释它为何会自己张开。",
                )
            ]

    rows = _fetch_foreshadowing_trees("run-1", DummyRepo())

    assert len(rows) == 1
    assert rows[0].root_event_id == "evt-root-1"
    assert rows[0].status == "reinforced"


def test_fetch_diagnosis_returns_none_when_agent_result_missing(db_session) -> None:
    novel_id, run_id = create_run_with_chunks(db_session, texts=["伯安帮了柳婉儿。"], title="无诊断报告")

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is None


def test_fetch_diagnosis_uses_agent_analysis_expectation_as_single_contract(db_session) -> None:
    """诊断成功结果同时携带题材与风格标签与焦点合同（正式报告单一来源）"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2},
        genre_labels=["科幻"],
        style_labels=["严肃"],
        topic_labels={"0": "成长"},
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.genre_labels == ["科幻"]
    assert result.style_labels == ["严肃"]
    assert result.focus_structure == "single"
    assert result.focus_characters == ["沈砚"]


def test_fetch_diagnosis_keeps_missing_arc_scores_as_none(db_session) -> None:
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.arc_scores is None
    # 没有评分时名单不得冒充有效焦点合同
    assert result.focus_characters == []
    assert result.focus_structure is None


def test_fetch_diagnosis_keeps_missing_topic_labels_as_none(db_session) -> None:
    """缺少主题命名时不得对外暴露标签（关系行缺失读为空集合）"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2},
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert not result.topic_labels
    assert result.focus_characters == ["沈砚"]


def test_fetch_diagnosis_keeps_missing_genre_labels_as_none(db_session) -> None:
    """题材标签缺失时保留其余诊断字段"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2},
        style_labels=["严肃"],
        topic_labels={"0": "成长"},
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert not result.genre_labels
    assert result.style_labels == ["严肃"]


def test_fetch_diagnosis_keeps_missing_style_labels_as_none(db_session) -> None:
    """风格标签缺失时保留其余诊断字段"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2},
        genre_labels=["科幻"],
        topic_labels={"0": "成长"},
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.genre_labels == ["科幻"]
    assert not result.style_labels


def test_fetch_diagnosis_drops_invalid_controlled_labels(db_session) -> None:
    """读取层丢弃逻辑下沉为正式写面拒绝：非法受控标签写不进报告"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["伯安帮了柳婉儿。"], title="非法标签")

    with pytest.raises(ValueError):
        _publish_diagnosis(db_session, run_id, genre_labels=["bad-genre"])
    with pytest.raises(ValueError):
        _publish_diagnosis(db_session, run_id, style_labels=["bad-style"])


def test_fetch_diagnosis_normalizes_controlled_labels_before_returning(db_session) -> None:
    """带空白与重复的受控标签在正式写面归一，读取层不暴露脏数据"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        genre_labels=[" 科幻 ", "科幻", " "],
        style_labels=[" 严肃 ", "严肃"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.genre_labels == ["科幻"]
    assert result.style_labels == ["严肃"]


def test_fetch_diagnosis_blank_narrative_arc_type_is_none(db_session) -> None:
    """P3 回归：空白 narrative_arc_type 不应透传空串，读取层归一化为 None。"""
    novel_id, run_id = _diagnosis_scenario(db_session, narrative_arc_type="  ")

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.narrative_arc_type is None


def test_fetch_diagnosis_strips_narrative_arc_type_whitespace(db_session) -> None:
    """P3 回归：narrative_arc_type 首尾空白应被剥离，不把脏串写入诊断结果。"""
    novel_id, run_id = _diagnosis_scenario(db_session, narrative_arc_type=" 三幕式")

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.narrative_arc_type == "三幕式"


def test_fetch_diagnosis_drops_non_mapping_arc_scores(db_session) -> None:
    """读取层丢弃逻辑下沉为正式写面拒绝：评分引用的角色必须是本 run 的正式实体"""
    _novel_id, run_id = create_run_with_chunks(db_session, texts=["伯安帮了柳婉儿。"], title="非法评分名")

    with pytest.raises(ValueError):
        _publish_diagnosis(db_session, run_id, register_names=False, arc_scores={"贺伯安": 8.2})


def test_fetch_diagnosis_returns_partial_agent_row(db_session) -> None:
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2, "陆明": 7.4},
        main_characters=["沈砚", "陆明"],
        core_cast=["沈砚", "陆明"],
        diagnosis="诊断记录只包含当前已有字段",
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.diagnosis == "诊断记录只包含当前已有字段"
    assert not result.focus_characters


def test_fetch_diagnosis_returns_current_fields(db_session) -> None:
    """当前诊断字段按正式报告直接返回"""
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"沈砚": 8.2},
        genre_labels=["科幻"],
        style_labels=["严肃"],
        topic_labels={"0": "成长"},
        focus_structure="single",
        focus_characters=["沈砚"],
        main_characters=["沈砚"],
        core_cast=["沈砚"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.arc_scores == {"沈砚": 8.2}
    assert result.focus_structure == "single"
    assert result.focus_characters == ["沈砚"]


def test_fetch_diagnosis_preserves_distinct_graph_entity_names(db_session) -> None:
    novel_id, run_id = _diagnosis_scenario(
        db_session,
        arc_scores={"伯安": 7.2, "贺伯安": 8.3},
        genre_labels=["通用"],
        style_labels=["严肃"],
        topic_labels={"0": "成长"},
        focus_structure="dual",
        focus_characters=["伯安", "贺伯安"],
        main_characters=["伯安", "贺伯安"],
        core_cast=["伯安", "贺伯安"],
    )

    result = _diagnosis_result(db_session, novel_id, run_id)

    assert result is not None
    assert result.arc_scores == {"伯安": 7.2, "贺伯安": 8.3}
    assert result.focus_structure == "dual"
    assert result.focus_characters == ["伯安", "贺伯安"]
    assert result.main_characters == ["伯安", "贺伯安"]
    assert result.core_cast == ["伯安", "贺伯安"]


def test_fetch_characters_marks_focus_characters_and_keeps_center_scores():
    rows = []
    rows.extend(
        [_DummyRow(surface_name="\u7532", resolved_global_name="\u7532", role_function="\u5ba2\u4f53", emotion_score=0)]
        * 20
    )
    rows.extend(
        [_DummyRow(surface_name="\u4e59", resolved_global_name="\u4e59", role_function="\u4e3b\u4f53", emotion_score=0)]
        * 10
    )

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    with patch("src.api.services.results_queries.characters.build_name_resolution", return_value={}):
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
    rows.extend([_DummyRow(surface_name="甲", resolved_global_name="甲", role_function="主体", emotion_score=0)] * 3)
    rows.extend([_DummyRow(surface_name="乙", resolved_global_name="乙", role_function="客体", emotion_score=0)] * 2)
    rows.extend([_DummyRow(surface_name="丙", resolved_global_name="丙", role_function="帮助者", emotion_score=0)] * 1)

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    with patch("src.api.services.results_queries.characters.build_name_resolution", return_value={}):
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
        _DummyRow(surface_name="我", resolved_global_name="我", role_function="主体", emotion_score=0),
        _DummyRow(surface_name="沈砚", resolved_global_name="沈砚", role_function="主体", emotion_score=0),
    ]

    annotation_repo = _DummyAnnotationRepo(rows=rows)

    with patch("src.api.services.results_queries.characters.build_name_resolution", return_value={}):
        result = _fetch_characters(
            run_id="run-1",
            annotation_repo=annotation_repo,
            limit=None,
        )

    assert [char.name for char in result] == ["沈砚"]


def test_normalize_arc_scores_preserves_named_scores():
    arc_scores = {"monkey": 6.5, "hou_fei_bai": 8.0, "abacus": 4.0}

    assert normalize_arc_scores(arc_scores) == {
        "monkey": 6.5,
        "hou_fei_bai": 8.0,
        "abacus": 4.0,
    }


def test_normalize_arc_scores_returns_none_when_payload_is_not_named_mapping():
    assert normalize_arc_scores([8.0, 6.0]) is None


def test_fetch_character_relations_deduplicates_across_chunks():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(from_name="贺伯安", to_name="二妈妈", relation_type="家族", last_seen_chapter=3),
            ExportRelationSnapshot(from_name="贺伯安", to_name="林立果", relation_type="盟友", last_seen_chapter=5),
        ]
    )

    with patch(
        "src.fact_graph.read.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert len(result) == 2

    rel1 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "二妈妈")
    assert rel1.chapter_id == 3
    assert rel1.type == "家族"
    assert rel1.change == "汇总"

    rel2 = next(r for r in result if r.from_char == "贺伯安" and r.to_char == "林立果")
    assert rel2.chapter_id == 5
    assert rel2.type == "盟友"


def test_fetch_character_relations_skips_inactive_current_relations():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                from_name="贺伯安",
                to_name="二妈妈",
                relation_type="家族",
                last_seen_chapter=3,
                is_active=False,
            ),
            ExportRelationSnapshot(
                from_name="贺伯安",
                to_name="林立果",
                relation_type="盟友",
                last_seen_chapter=5,
                is_active=True,
            ),
        ]
    )

    with patch(
        "src.fact_graph.read.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert [(item.from_char, item.to_char) for item in result] == [("贺伯安", "林立果")]


def test_fetch_character_relations_uses_last_seen_chapter_id():
    annotation_repo = _DummyAnnotationRepo2()
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(from_name="张三", to_name="李四", relation_type="朋友", last_seen_chapter=15),
        ]
    )

    with patch(
        "src.fact_graph.read.KnowledgeGraphAuthorityService.from_session",
        return_value=SimpleNamespace(assert_graph_ready=lambda _run_id: None),
    ):
        result = _fetch_character_relations(
            run_id="run-1",
            annotation_repo=annotation_repo,
            export_graph_view=export_graph_view,
        )

    assert len(result) == 1
    assert result[0].chapter_id == 15
    assert result[0].change == "汇总"


def test_fetch_character_relations_raises_when_pending_exists_and_graph_empty():
    annotation_repo = _DummyAnnotationRepo2()
    with patch(
        "src.fact_graph.read.KnowledgeGraphAuthorityService.from_session",
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
        "src.fact_graph.read.KnowledgeGraphAuthorityService.from_session",
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
                relation_id="relation-1",
                from_name="贺铮",
                to_name="伯安",
                relation_type="隶属",
                first_seen_chapter=2,
                last_seen_chapter=9,
            ),
            ExportRelationSnapshot(
                relation_id="relation-2",
                from_name="贺铮",
                to_name="伯安",
                relation_type="家族",
                first_seen_chapter=2,
                last_seen_chapter=9,
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
    assert result[0].rel_type == "隶属"


def test_fetch_hierarchical_relations_filters_unknown_graph_endpoint():
    export_graph_view = ExportGraphAuthorityView(
        current_relations=[
            ExportRelationSnapshot(
                relation_id=10,
                from_name="柳婉儿",
                to_name="陌生人",
                relation_type="隶属",
                first_seen_chapter=1,
                last_seen_chapter=4,
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
                relation_id="relation-1",
                from_name="老贺",
                to_name="伯安",
                relation_type="隶属",
                first_seen_chapter=2,
                last_seen_chapter=9,
                is_active=False,
            ),
            ExportRelationSnapshot(
                relation_id="relation-2",
                from_name="老贺",
                to_name="阿明",
                relation_type="隶属",
                first_seen_chapter=3,
                last_seen_chapter=10,
                is_active=True,
            ),
        ]
    )

    result = _fetch_hierarchical_relations(
        run_id="run-1",
        export_graph_view=export_graph_view,
        valid_character_names={"老贺", "伯安", "阿明"},
    )

    assert [(item.rel_id, item.from_entity, item.to_entity) for item in result] == [("relation-2", "老贺", "阿明")]


def test_fetch_hierarchical_relations_keeps_supported_non_character_hierarchy():
    export_graph_view = ExportGraphAuthorityView(
        canonical_entities=[
            SimpleNamespace(name="伯安", entity_type="character"),
            SimpleNamespace(name="贺家", entity_type="organization"),
            SimpleNamespace(name="赵甲卫", entity_type="group"),
        ],
        current_relations=[
            ExportRelationSnapshot(
                relation_id="relation-11",
                from_name="伯安",
                to_name="贺家",
                relation_type="隶属",
                first_seen_chapter=2,
                last_seen_chapter=9,
                is_active=True,
            ),
            ExportRelationSnapshot(
                relation_id="relation-12",
                from_name="赵甲卫",
                to_name="贺家",
                relation_type="隶属",
                first_seen_chapter=3,
                last_seen_chapter=10,
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
        ("relation-11", "隶属", "伯安", "贺家"),
        ("relation-12", "隶属", "赵甲卫", "贺家"),
    ]


def test_fetch_chapter_annotations_builds_relations_from_export_authority_view():
    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chapter_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chapter_id=3,
                    emotional_valence=1,
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=False,
                    is_strong_setup=False,
                    foreshadowing_desc=None,
                    why_unresolved_now=None,
                )
            ]

        def fetch_chapter_characters_full(self, _run_id):
            return []

        def fetch_chapter_dialogues_full(self, _run_id):
            return []

    annotation_repo = _AnnotationRepoWithChunkRows()
    export_graph_view = ExportGraphAuthorityView(
        graph_changes=[
            GraphChange(
                change_id="relation:101",
                change_kind="relation",
                chapter_id=1,
                chapter_order=1,
                fact_id="fact-101",
                effective_chapter_id=3,
                confidence="high",
                changes=[
                    {
                        "change_kind": "assert",
                        "before": None,
                        "after": {"relation_type": "父子", "is_active": True},
                        "fact_id": "fact-101",
                        "chunk_id": 3,
                    }
                ],
                from_entity_id=1,
                to_entity_id=2,
                from_name="贺铮",
                to_name="伯安",
                relation_type="父子",
                directionality="directed",
            )
        ]
    )

    result = _fetch_chapter_annotations(
        run_id="run-1",
        annotation_repo=annotation_repo,
        valid_character_names={"贺铮", "伯安"},
        export_graph_view=export_graph_view,
    )

    assert len(result) == 1
    assert result[0].is_strong_setup is False
    assert result[0].why_unresolved_now is None
    # 2026-09-14 expected_payoff_family 全链退役（响应模型删字段）；按新合同换算为
    # 保留字段 payoff_likelihood/foreshadowing_root_event_id 在无伏笔行时同样保持 None
    assert result[0].payoff_likelihood is None
    assert result[0].foreshadowing_root_event_id is None
    assert len(result[0].relations) == 1
    assert result[0].relations[0].from_char == "贺铮"
    assert result[0].relations[0].to_char == "伯安"
    assert result[0].relations[0].type == "父子"
    assert result[0].relations[0].change == "assert"


def test_fetch_chapter_annotations_uses_explicit_database_graph_view():
    """2026-08-05 用于验证 chunk 展开结果只读取显式数据库图视图"""

    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chapter_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chapter_id=3,
                    emotional_valence=1,
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=True,
                    is_strong_setup=True,
                    foreshadowing_desc=(
                        "玉佩发热 - 具体钩子：玉佩出现异常发热。未闭合原因：当前还没有解释它为何会发热。"
                    ),
                    why_unresolved_now="当前还没有解释它为何会发热。",
                    expected_payoff_family="能力触发",
                )
            ]

        def fetch_chapter_characters_full(self, _run_id):
            return []

        def fetch_chapter_dialogues_full(self, _run_id):
            return []

    result = _fetch_chapter_annotations(
        run_id="run-1",
        annotation_repo=_AnnotationRepoWithChunkRows(),
        export_graph_view=ExportGraphAuthorityView(),
    )

    assert len(result) == 1
    assert result[0].chapter_id == 3
    assert result[0].is_strong_setup is True
    assert result[0].relations == []


def test_fetch_chapter_annotations_propagates_database_graph_failure(monkeypatch):
    """2026-08-05 用于验证 chunk 消费者不会在数据库图失败时降级读取"""

    class _AnnotationRepoWithChunkRows(_DummyAnnotationRepo2):
        def fetch_chapter_annotations_full(self, _run_id):
            return [
                _DummyRow(
                    chapter_id=3,
                    emotional_valence="正向",
                    event_type="冲突",
                    pivot_moment=True,
                    cliffhanger=False,
                    has_foreshadowing=False,
                    is_strong_setup=False,
                    foreshadowing_desc=None,
                    why_unresolved_now=None,
                    expected_payoff_family=None,
                )
            ]

        def fetch_chapter_characters_full(self, _run_id):
            return []

        def fetch_chapter_dialogues_full(self, _run_id):
            return []

    annotation_repo = _AnnotationRepoWithChunkRows()

    class _GraphUnavailableService:
        def build_export_view(self, _run_id):
            raise GraphReadinessError("graph participant state is stale or incomplete")

    monkeypatch.setattr(
        "src.api.services.results_queries.chapters.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: _GraphUnavailableService(),
    )

    with pytest.raises(GraphReadinessError, match="graph participant state is stale"):
        _fetch_chapter_annotations(
            run_id="run-1",
            annotation_repo=annotation_repo,
        )


@pytest.mark.parametrize("emotion", ["正向", "1", True, 3])
def test_chapter_results_reject_legacy_or_invalid_emotion_values(emotion: object) -> None:
    """查询不能把旧文字值或非法分值静默伪装成中性结果"""
    repo = MagicMock()
    repo.fetch_chapter_annotations_full.return_value = [SimpleNamespace(chapter_id=1, emotional_valence=emotion)]
    repo.fetch_chapter_characters_full.return_value = []
    repo.fetch_chapter_dialogues_full.return_value = []
    with pytest.raises(ValueError, match="emotion="):
        _fetch_chapter_annotations("run-1", repo, export_graph_view=ExportGraphAuthorityView())
