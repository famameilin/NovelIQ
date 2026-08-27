from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.api.exceptions import GraphReadinessError
from src.metrics.aggregate.fetchers import fetch_character_data, fetch_relation_data


class _DummyAnnotationRepo:
    def __init__(self, character_rows=None, emotion_rows=None):
        self.session = object()
        self._character_rows = character_rows or [
            SimpleNamespace(
                name="主角",
                surface_name="主角",
                resolved_global_name="主角",
                role_function="主体",
                emotion_score="mild_positive",
            ),
            SimpleNamespace(
                name="同伴",
                surface_name="同伴",
                resolved_global_name="同伴",
                role_function="助手",
                emotion_score=None,
            ),
        ]
        self._emotion_rows = emotion_rows or [
            SimpleNamespace(surface_name="主角", resolved_global_name="主角", emotion_score="mild_positive"),
            SimpleNamespace(surface_name="主角", resolved_global_name="主角", emotion_score="mild_negative"),
            SimpleNamespace(surface_name="同伴", resolved_global_name="同伴", emotion_score="mild_positive"),
        ]

    def fetch_characters_with_scores(self, run_id):
        return self._character_rows

    def fetch_character_emotion_sequence(self, run_id):
        return self._emotion_rows


def test_fetch_character_data_uses_level1_canonical_entities_instead_of_graph_participants():
    annotation_repo = _DummyAnnotationRepo()
    mock_service = MagicMock()
    mock_service.build_graph_view.return_value = SimpleNamespace(
        participant_states=[
            SimpleNamespace(name="主角", status="active", primary_role_function="主体"),
            SimpleNamespace(name="同伴", status="active", primary_role_function="助手"),
        ]
    )
    mock_service.build_level1_snapshot.return_value = SimpleNamespace(
        canonical_entities=[
            SimpleNamespace(name="主角", entity_type="character", status="active", primary_role_function="主体"),
            SimpleNamespace(name="同伴", entity_type="character", status="active", primary_role_function="助手"),
            SimpleNamespace(name="路人甲", entity_type="character", status="active", primary_role_function=None),
            SimpleNamespace(name="旧敌", entity_type="character", status="inactive", primary_role_function="反对者"),
            SimpleNamespace(name="古槐", entity_type="location", status="active", primary_role_function=None),
        ],
    )

    with patch(
        "src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=mock_service,
    ) as from_session:
        data = fetch_character_data(annotation_repo, "run-1")

    from_session.assert_called_once_with(annotation_repo.session)
    mock_service.build_level1_snapshot.assert_called_once_with("run-1")
    assert data.characters == [
        ("主角", "主体", 1),
        ("同伴", "助手", 0),
        ("路人甲", "其他", 0),
    ]
    assert data.char_emotion_scores == [
        ("主角", [1.0, -1.0]),
        ("同伴", [1.0]),
    ]
    mock_service.build_graph_view.assert_not_called()


def test_fetch_character_data_uses_explicit_resolved_graph_name():
    annotation_repo = _DummyAnnotationRepo(
        character_rows=[
            SimpleNamespace(
                name="灰衣人",
                surface_name="灰衣人",
                resolved_global_name="白芷",
                role_function="主体",
                emotion_score="mild_positive",
            ),
            SimpleNamespace(
                name="同伴",
                surface_name="同伴",
                resolved_global_name="同伴",
                role_function="助手",
                emotion_score=None,
            ),
        ],
        emotion_rows=[
            SimpleNamespace(surface_name="灰衣人", resolved_global_name="白芷", emotion_score="mild_positive"),
            SimpleNamespace(surface_name="灰衣人", resolved_global_name="白芷", emotion_score="mild_negative"),
            SimpleNamespace(surface_name="同伴", resolved_global_name="同伴", emotion_score="mild_positive"),
        ],
    )
    mock_service = MagicMock()
    mock_service.build_graph_view.return_value = SimpleNamespace(
        participant_states=[
            SimpleNamespace(name="白芷", status="active", primary_role_function="主体"),
            SimpleNamespace(name="同伴", status="active", primary_role_function="助手"),
        ]
    )
    mock_service.build_level1_snapshot.return_value = SimpleNamespace(
        canonical_entities=[
            SimpleNamespace(name="白芷", entity_type="character", status="active", primary_role_function="主体"),
            SimpleNamespace(name="同伴", entity_type="character", status="active", primary_role_function="助手"),
        ],
    )

    with patch(
        "src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=mock_service,
    ):
        data = fetch_character_data(annotation_repo, "run-alias")

    assert data.characters == [
        ("白芷", "主体", 1),
        ("同伴", "助手", 0),
    ]
    assert data.char_emotion_scores == [
        ("白芷", [1.0, -1.0]),
        ("同伴", [1.0]),
    ]
    mock_service.build_graph_view.assert_not_called()


def test_fetch_character_data_skips_unresolved_reference_rows() -> None:
    annotation_repo = _DummyAnnotationRepo(
        character_rows=[
            SimpleNamespace(
                name="我",
                surface_name="我",
                resolved_global_name=None,
                role_function="主体",
                emotion_score="mild_positive",
            ),
            SimpleNamespace(
                name="汪淼",
                surface_name="汪淼",
                resolved_global_name="汪淼",
                role_function="主体",
                emotion_score="mild_negative",
            ),
        ],
        emotion_rows=[
            SimpleNamespace(surface_name="我", resolved_global_name=None, emotion_score="mild_positive"),
            SimpleNamespace(surface_name="汪淼", resolved_global_name="汪淼", emotion_score="mild_negative"),
        ],
    )
    mock_service = MagicMock()
    mock_service.build_level1_snapshot.return_value = SimpleNamespace(
        canonical_entities=[
            SimpleNamespace(name="汪淼", entity_type="character", status="active", primary_role_function="主体"),
        ],
    )

    with patch(
        "src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=mock_service,
    ):
        data = fetch_character_data(annotation_repo, "run-pronoun")

    assert data.characters == [("汪淼", "主体", -1)]
    assert data.char_emotion_scores == [("汪淼", [-1.0])]


def test_fetch_relation_data_propagates_database_graph_readiness_failure():
    annotation_repo = _DummyAnnotationRepo()
    mock_service = MagicMock()
    mock_service.assert_graph_ready = MagicMock(
        side_effect=GraphReadinessError("database graph is unavailable for the requested run.")
    )
    mock_service.build_representative_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[],
        graph_changes=[],
    )

    with patch("src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session", return_value=mock_service):
        with pytest.raises(GraphReadinessError, match="database graph is unavailable"):
            fetch_relation_data(annotation_repo, "run-1")


def test_fetch_relation_data_allows_empty_database_graph():
    """
    修改时间: 2026-04-29
    任务: 修复全量测试阻塞
    修改原因: GraphAuthorityView 正式合同包含 participant_states，测试 mock 需要补齐该字段。
    """

    annotation_repo = _DummyAnnotationRepo()
    mock_service = MagicMock()
    mock_service.assert_graph_ready = MagicMock()
    mock_service.build_representative_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[],
        graph_changes=[],
        participant_states=[],
    )

    with patch("src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session", return_value=mock_service):
        data = fetch_relation_data(annotation_repo, "run-1")

    assert data.relations == []
    assert data.full_relations == []


def test_fetch_relation_data_consumes_authority_view():
    """
    修改时间: 2026-04-29
    任务: 修复全量测试阻塞
    修改原因: GraphAuthorityView 正式合同包含 participant_states，测试 mock 需要补齐该字段。
    """

    annotation_repo = _DummyAnnotationRepo()
    mock_service = MagicMock()
    mock_service.assert_graph_ready = MagicMock()
    mock_service.build_representative_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[
            SimpleNamespace(from_name="主角", to_name="反派"),
        ],
        graph_changes=[
            SimpleNamespace(
                change_kind="relation",
                from_name="主角",
                to_name="反派",
                relation_type="敌对",
                changes=[{"change_kind": "reinforce"}],
            ),
            SimpleNamespace(
                change_kind="relation",
                from_name="主角",
                to_name="同伴",
                relation_type="盟友",
                changes=[{"change_kind": "assert"}],
            ),
        ],
        # P4：人物网络只消费 character 参与者；mock 需补 entity_type
        participant_states=[
            SimpleNamespace(name="主角", entity_type="character"),
            SimpleNamespace(name="反派", entity_type="character"),
            SimpleNamespace(name="同伴", entity_type="character"),
        ],
    )

    with patch(
        "src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=mock_service,
    ) as from_session:
        data = fetch_relation_data(annotation_repo, "run-graph")

    from_session.assert_called_once_with(annotation_repo.session)
    mock_service.build_representative_graph_view.assert_called_once_with("run-graph")
    assert data.relations == [("主角", "反派")]
    assert data.full_relations == [
        ("主角", "反派", "敌对", "reinforce"),
        ("主角", "同伴", "盟友", "assert"),
    ]


def test_fetch_relation_data_propagates_graph_failure_before_using_non_empty_view():
    annotation_repo = _DummyAnnotationRepo()
    mock_service = MagicMock()
    mock_service.assert_graph_ready = MagicMock(
        side_effect=GraphReadinessError("database graph is unavailable for the requested run.")
    )
    mock_service.build_representative_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[SimpleNamespace(from_name="主角", to_name="反派")],
        graph_changes=[
            SimpleNamespace(
                change_kind="relation",
                from_name="主角",
                to_name="反派",
                relation_type="敌对",
                changes=[{"change_kind": "reinforce"}],
            )
        ],
    )

    with patch("src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session", return_value=mock_service):
        with pytest.raises(GraphReadinessError, match="database graph is unavailable"):
            fetch_relation_data(annotation_repo, "run-partial")
