import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.api.exceptions import GraphReadinessError
from src.knowledge.authority import GraphAuthorityReport, GraphAuthorityView, GraphQualitySignals, GraphSharedSummary
from src.models.cloud import build_diagnosis_payload
from src.storage.models import Novel
from src.storage.repositories.annotation.foreshadowing_threads import ForeshadowingThreadView


def test_diagnosis_prompt_does_not_require_foreshadow_expectation_output() -> None:
    """
    创建时间: 2026-04-29
    任务: foreshadow-expectation-v2
    新建原因: diagnosis LLM 不再负责生成 foreshadow_expectation，prompt 示例不能继续把它列为输出字段。
    """

    prompt_path = Path(__file__).resolve().parents[2] / "config" / "prompts" / "diagnose.txt"
    prompt = prompt_path.read_text(encoding="utf-8")

    assert '"foreshadow_expectation":' not in prompt
    assert "你不需要输出、改写或重新估算这个字段" in prompt


def test_build_diagnosis_payload_reads_three_layer_checkpoint(db_session):
    run_id = "runpayl"
    novel_id = "novpayl"
    db_session.add(Novel(novel_id=novel_id, filename="test.txt", file_path="data/test.txt", file_size=128))
    db_session.commit()
    db_session.execute(
        text(
            "INSERT INTO analysis_runs ("
            "run_id, novel_id, source_path, title, status, progress, current, total, "
            "task_kind, cancel_requested, created_at, updated_at"
            ") VALUES (:run_id, :novel_id, 'test', 'Test', 'pending', 0, 0, 100, 'analysis', false, NOW(), NOW())"
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
        "unresolved_references": [],
        "reference_resolutions": [["我", "bai_zhi"]],
        "review_status": [],
        "pending_relations": [],
        "entity_types": {},
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
    assert "reference_contract_version" not in payload
    assert "foreshadow_expectation" in payload
    assert "foreshadowing_threads" in payload
    assert "graph_summary" in payload
    assert "graph_quality_report" in payload
    assert set(payload["graph_summary"].keys()) == {"node_count", "edge_count", "density"}


def test_build_diagnosis_payload_uses_summary_quality_report_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-29
    任务: split-genre-style-labels-review-fixes
    说明: summary-only/shared-signal 入口允许使用轻量 session stand-in；
          这类入口拿不到 chunk 文本时，genre_labels 应明确回退为 `["通用"]`，但不能打断 graph signal 校验。
    """
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

        def fetch_foreshadowing_threads(self, *_args, **_kwargs):
            return []

        def calculate_foreshadow_expectation(self, *_args, **_kwargs):
            return 0.42

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
    assert payload["foreshadow_expectation"] == 0.42
    assert payload["genre_labels"] == ["通用"]
    assert payload["foreshadowing_threads"] == []
    assert payload["graph_summary"] == {"node_count": 2, "edge_count": 1, "density": 0.5}
    assert payload["graph_quality_report"] == {"conflict_count": 0, "low_confidence_count": 1}


def test_build_diagnosis_payload_falls_back_when_graph_projection_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-05-02
    任务: diagnosis-graph-readiness-fallback
    新建原因: diagnosis 只消费 graph-owned aggregate signals；当 authority report 因 pending projection 不可读时，
              payload 应降级为零值共享信号并继续构建，而不是让整条任务失败。
    """

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

        def fetch_foreshadowing_threads(self, *_args, **_kwargs):
            return []

        def calculate_foreshadow_expectation(self, *_args, **_kwargs):
            return 0.0

        def fetch_stage_summaries(self, *_args, **_kwargs):
            return []

        def fetch_topic_words(self, *_args, **_kwargs):
            return []

        def fetch_character_disambig_data(self, *_args, **_kwargs):
            return (["白芷"], {"蒙面人": "白芷"})

    class FakeAuthorityService:
        def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
            assert run_id == "run-graph-pending"
            raise GraphReadinessError(
                "graph projection is still pending; finish projection before reading graph-derived authority views."
            )

        def build_graph_view(self, *_args, **_kwargs):
            raise AssertionError("diagnosis should not depend on full GraphAuthorityView")

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    payload = build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-graph-pending")

    assert payload["known_characters"] == ["白芷"]
    assert payload["alias_merges"] == {"蒙面人": "白芷"}
    assert payload["graph_summary"] == {"node_count": 0, "edge_count": 0, "density": 0.0}
    assert payload["graph_quality_report"] == {"conflict_count": 0, "low_confidence_count": 0}


def test_build_diagnosis_payload_raises_when_graph_projection_has_blocking_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    创建时间: 2026-05-02
    任务: diagnosis-graph-readiness-fallback
    新建原因: graph projection 的真实 failed rows 不能被降级为空图共享信号，
              否则 diagnosis 会把硬失败误当成 0 节点图继续下发给云端模型。
    """

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

        def fetch_foreshadowing_threads(self, *_args, **_kwargs):
            return []

        def calculate_foreshadow_expectation(self, *_args, **_kwargs):
            return 0.0

        def fetch_stage_summaries(self, *_args, **_kwargs):
            return []

        def fetch_topic_words(self, *_args, **_kwargs):
            return []

        def fetch_character_disambig_data(self, *_args, **_kwargs):
            return (["白芷"], {"蒙面人": "白芷"})

    class FakeAuthorityService:
        def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
            assert run_id == "run-graph-failed"
            raise GraphReadinessError(
                "graph projection has failed rows; "
                "resolve projection failures before reading graph-derived authority views."
            )

        def build_graph_view(self, *_args, **_kwargs):
            raise AssertionError("diagnosis should not depend on full GraphAuthorityView")

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    with pytest.raises(GraphReadinessError, match="graph projection has failed rows"):
        build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-graph-failed")


def test_build_diagnosis_payload_preserves_thread_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    创建时间: 2026-04-29
    任务: fix-phase2-medium-confidence-thread-semantics
    新建原因: diagnosis payload 会把 foreshadowing_threads 继续透传给下游消费者；
              thread confidence 必须保留下来，避免 medium thread 在展示层再次和 high 混同。
    """

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

        def fetch_foreshadowing_threads(self, *_args, **_kwargs):
            return [
                ForeshadowingThreadView(
                    setup_id="setup-1",
                    first_chunk_id=3,
                    last_chunk_id=3,
                    anchor_chunk_ids=[3],
                    setup_summary="雨夜铜铃自行作响",
                    setup_kind="异常物件",
                    expected_payoff_family="规则兑现",
                    payoff_likelihood="high",
                    confidence="medium",
                    strength="medium",
                    status="open",
                    active=True,
                    latest_reason="具体钩子：铜铃在雨夜自行作响。未闭合原因：当前还没有解释它为何会自己作响。",
                    latest_why_unresolved_now="当前还没有解释它为何会自己作响。",
                )
            ]

        def calculate_foreshadow_expectation(self, *_args, **_kwargs):
            return 0.55

        def fetch_stage_summaries(self, *_args, **_kwargs):
            return []

        def fetch_topic_words(self, *_args, **_kwargs):
            return []

        def fetch_character_disambig_data(self, *_args, **_kwargs):
            return (["白芷"], {"蒙面人": "白芷"})

    class FakeAuthorityService:
        def build_graph_report(self, run_id: str) -> GraphAuthorityReport:
            assert run_id == "run-thread-confidence"
            return GraphAuthorityReport(
                summary=GraphSharedSummary(node_count=1, edge_count=0, density=0.0),
                quality=GraphQualitySignals(conflict_count=0, low_confidence_count=0),
            )

        def build_graph_view(self, *_args, **_kwargs):
            raise AssertionError("diagnosis should not depend on full GraphAuthorityView")

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    payload = build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-thread-confidence")

    assert payload["foreshadow_expectation"] == 0.55
    assert payload["foreshadowing_threads"][0]["setup_id"] == "setup-1"
    assert payload["foreshadowing_threads"][0]["confidence"] == "medium"
    assert payload["foreshadowing_threads"][0]["strength"] == "medium"


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

        def fetch_foreshadowing_threads(self, *_args, **_kwargs):
            return []

        def calculate_foreshadow_expectation(self, *_args, **_kwargs):
            return None

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
                participant_states=[],
            )

    monkeypatch.setattr("src.models.cloud.payload.DiagnosisRepository", FakeDiagnosisRepository)
    monkeypatch.setattr("src.models.cloud.payload._get_total_topic_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        "src.models.cloud.payload.KnowledgeGraphAuthorityService.from_session",
        lambda *_args, **_kwargs: FakeAuthorityService(),
    )

    with pytest.raises(TypeError, match="shared graph signal consumers require GraphAuthorityReport"):
        build_diagnosis_payload(SimpleNamespace(), novel_id="novel-1", run_id="run-invalid-shared-graph")
