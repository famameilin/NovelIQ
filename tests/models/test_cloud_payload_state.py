import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.knowledge.authority import GraphAuthorityReport, GraphAuthorityView, GraphQualitySignals, GraphSharedSummary
from src.models.cloud import build_diagnosis_payload
from src.storage.models import Novel


def test_build_diagnosis_payload_reads_three_layer_checkpoint(db_session):
    run_id = "runpayl"
    novel_id = "novpayl"
    db_session.add(Novel(novel_id=novel_id, filename="test.txt", file_path="data/test.txt", file_size=128))
    db_session.commit()
    db_session.execute(
        text(
            "INSERT INTO analysis_runs (run_id, novel_id, source_path, title, status, progress, current, total, task_kind, cancel_requested, created_at, updated_at) "
            "VALUES (:run_id, :novel_id, 'test', 'Test', 'pending', 0, 0, 100, 'analysis', false, NOW(), NOW())"
        ),
        {"run_id": run_id, "novel_id": novel_id},
    )
    state_payload = {
        "discovered_names": ["masked_person", "bai_zhi", "monkey", "hou_fei_bai"],
        "known_canonical_names": ["bai_zhi", "hou_fei_bai"],
        "alias_merges": [
            ["masked_person", "bai_zhi"],
            ["monkey", "hou_fei_bai"],
        ],
        "review_status": [],
        "pending_relations": [],
        "version": 1,
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    db_session.execute(
        text(
            """
            INSERT INTO disambig_checkpoint (run_id, state_json, updated_at)
            VALUES (:run_id, :state_json, :updated_at)
            """
        ),
        {
            "run_id": run_id,
            "state_json": json.dumps(state_payload, ensure_ascii=False),
            "updated_at": 1.0,
        },
    )
    db_session.commit()

    payload = build_diagnosis_payload(db_session, novel_id=novel_id, run_id=run_id)

    assert payload["known_characters"] == ["bai_zhi", "hou_fei_bai"]
    assert payload["alias_merges"] == {
        "masked_person": "bai_zhi",
        "monkey": "hou_fei_bai",
    }
    assert "graph_summary" in payload
    assert "graph_quality_report" in payload
    assert set(payload["graph_summary"].keys()) == {"node_count", "edge_count", "density"}


def test_build_diagnosis_payload_uses_summary_quality_report_view(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDiagnosisRepository:
        def __init__(self, session) -> None:
            self.session = session

        def fetch_pivot_blocks(self, *_args, **_kwargs):
            return []

        def fetch_pivot_moments(self, *_args, **_kwargs):
            return []

        def fetch_high_tension_chunks(self, *_args, **_kwargs):
            return []

        def fetch_relation_changes(self, *_args, **_kwargs):
            return []

        def fetch_foreshadowing_chunks(self, *_args, **_kwargs):
            return []

        def fetch_stage_summaries(self, *_args, **_kwargs):
            return []

        def fetch_topic_words(self, *_args, **_kwargs):
            return []

        def fetch_character_disambig_data(self, *_args, **_kwargs):
            return (["白芷"], {"蒙面人": "白芷"})

    class FakeAuthorityService:
        def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
            assert run_id == "run-summary-only"
            return GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=2, edge_count=1, density=0.5),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=1),
            )

        def build_graph_view(self, *_args, **_kwargs):
            raise AssertionError("diagnosis should not depend on full GraphAuthorityView")

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    payload = build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-summary-only")

    assert payload["known_characters"] == ["白芷"]
    assert payload["alias_merges"] == {"蒙面人": "白芷"}
    assert payload["graph_summary"] == {"node_count": 2, "edge_count": 1, "density": 0.5}
    assert payload["graph_quality_report"] == {"conflict_count": 0, "low_confidence_count": 1}


def test_build_diagnosis_payload_rejects_full_graph_view_from_shared_signal_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDiagnosisRepository:
        def __init__(self, session) -> None:
            self.session = session

        def fetch_pivot_blocks(self, *_args, **_kwargs):
            return []

        def fetch_pivot_moments(self, *_args, **_kwargs):
            return []

        def fetch_high_tension_chunks(self, *_args, **_kwargs):
            return []

        def fetch_relation_changes(self, *_args, **_kwargs):
            return []

        def fetch_foreshadowing_chunks(self, *_args, **_kwargs):
            return []

        def fetch_stage_summaries(self, *_args, **_kwargs):
            return []

        def fetch_topic_words(self, *_args, **_kwargs):
            return []

        def fetch_character_disambig_data(self, *_args, **_kwargs):
            return (["白芷"], {"蒙面人": "白芷"})

    class FakeAuthorityService:
        def build_graph_report(self, run_id: str) -> GraphAuthorityView:
            assert run_id == "run-invalid-shared-graph"
            return GraphAuthorityView(
                canonical_entities=[],
                confirmed_relations=[],
                relation_events=[],
                stable_states=[],
            )

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    with pytest.raises(TypeError, match="shared graph signal consumers require GraphAuthorityReport"):
        build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-invalid-shared-graph")
