from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.api.exceptions import GraphReadinessError
from src.metrics.aggregate.fetchers import fetch_character_data, fetch_relation_data


class _DummyAnnotationRepo:
    def __init__(self, pending=None, character_rows=None, emotion_rows=None):
        self.session = object()
        self._pending = pending or []
        self._character_rows = character_rows or [
            ("主角", "主体", "mild_positive"),
            ("同伴", "助手", None),
        ]
        self._emotion_rows = emotion_rows or [
            ("主角", "mild_positive"),
            ("主角", "mild_negative"),
            ("同伴", "mild_positive"),
        ]

    def fetch_pending_chunk_relations(self, run_id, to_chunk=None, limit=200):
        return self._pending

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
        alias_mappings=[],
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


def test_fetch_character_data_normalizes_alias_scores_to_canonical_name():
    annotation_repo = _DummyAnnotationRepo(
        character_rows=[
            ("灰衣人", "主体", "mild_positive"),
            ("同伴", "助手", None),
        ],
        emotion_rows=[
            ("灰衣人", "mild_positive"),
            ("灰衣人", "mild_negative"),
            ("同伴", "mild_positive"),
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
        alias_mappings=[
            SimpleNamespace(alias="灰衣人", canonical="白芷"),
        ],
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


def test_fetch_relation_data_raises_when_pending_exists_and_graph_empty():
    annotation_repo = _DummyAnnotationRepo(pending=[object()])
    mock_service = MagicMock()
    mock_service.assert_graph_projection_ready = MagicMock(
        side_effect=GraphReadinessError(
            "graph projection is still pending; finish projection before reading graph-derived authority views."
        )
    )
    mock_service.build_graph_view.return_value = SimpleNamespace(confirmed_relations=[], relation_events=[])

    with patch("src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session", return_value=mock_service):
        with pytest.raises(GraphReadinessError, match="graph projection is still pending"):
            fetch_relation_data(annotation_repo, "run-1")


def test_fetch_relation_data_allows_empty_graph_when_no_pending():
    """
    修改时间: 2026-04-29
    任务: 修复全量测试阻塞
    修改原因: GraphAuthorityView 正式合同包含 participant_states，测试 mock 需要补齐该字段。
    """

    annotation_repo = _DummyAnnotationRepo(pending=[])
    mock_service = MagicMock()
    mock_service.assert_graph_projection_ready = MagicMock()
    mock_service.build_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[],
        relation_events=[],
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

    annotation_repo = _DummyAnnotationRepo(pending=[])
    mock_service = MagicMock()
    mock_service.assert_graph_projection_ready = MagicMock()
    mock_service.build_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[
            SimpleNamespace(from_name="主角", to_name="反派"),
        ],
        relation_events=[
            SimpleNamespace(from_name="主角", to_name="反派", relation_type="敌对", change_type="强化"),
            SimpleNamespace(from_name="主角", to_name="同伴", relation_type="盟友", change_type="新建"),
        ],
        participant_states=[],
    )

    with patch(
        "src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session",
        return_value=mock_service,
    ) as from_session:
        data = fetch_relation_data(annotation_repo, "run-graph")

    from_session.assert_called_once_with(annotation_repo.session)
    mock_service.build_graph_view.assert_called_once_with("run-graph")
    assert data.relations == [("主角", "反派")]
    assert data.full_relations == [
        ("主角", "反派", "敌对", "强化"),
        ("主角", "同伴", "盟友", "新建"),
    ]


def test_fetch_relation_data_rejects_partial_pending_graph_even_when_view_is_non_empty():
    annotation_repo = _DummyAnnotationRepo(pending=[object()])
    mock_service = MagicMock()
    mock_service.assert_graph_projection_ready = MagicMock(
        side_effect=GraphReadinessError(
            "graph projection is still pending; finish projection before reading graph-derived authority views."
        )
    )
    mock_service.build_graph_view.return_value = SimpleNamespace(
        confirmed_relations=[SimpleNamespace(from_name="主角", to_name="反派")],
        relation_events=[SimpleNamespace(from_name="主角", to_name="反派", relation_type="敌对", change_type="强化")],
    )

    with patch("src.metrics.aggregate.fetchers.KnowledgeGraphAuthorityService.from_session", return_value=mock_service):
        with pytest.raises(GraphReadinessError, match="graph projection is still pending"):
            fetch_relation_data(annotation_repo, "run-partial")
