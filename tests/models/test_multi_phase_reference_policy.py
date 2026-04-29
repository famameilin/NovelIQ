import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.local.annotation.multi_phase import (
    _MultiPhaseExecutionContext,
    _resolve_known_characters,
    _resolve_phase4_bundle,
    _run_phase4_from_context,
)
from src.models.local.schema import CharacterSnapshot, ChunkAnnotation
from src.rag import EvidenceBundle, EvidenceRequest


def _character(name: str, *, resolved_global_name: str | None = None) -> CharacterSnapshot:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: 构造最小角色快照，锁定 Phase1 raw 角色进入 known_characters 前的准入过滤。
    """
    return CharacterSnapshot(
        name=name,
        resolved_global_name=resolved_global_name,
        role_function="主体",
        action="出现",
        action_type="出现",
        emotion_score="neutral",
    )


def test_resolve_known_characters_excludes_unresolved_pronoun() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: Phase1 输出 raw “我”时，后续 Phase 输入不能把它当成 known_character。
    """
    annotation = ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        characters=[_character("我"), _character("汪淼")],
    )

    assert _resolve_known_characters(annotation) == ["汪淼"]


def test_resolve_known_characters_allows_resolved_pronoun_target() -> None:
    """
    创建时间: 2026-04-29
    任务: 角色引用分层重构
    新建原因: “我 -> 汪淼”这类已解析引用只能让实名进入 known_characters。
    """
    annotation = ChunkAnnotation(
        emotional_valence="neutral",
        event_type="铺垫",
        pivot_moment=False,
        cliffhanger=False,
        has_foreshadowing=False,
        characters=[_character("我", resolved_global_name="汪淼")],
    )

    assert _resolve_known_characters(annotation) == ["汪淼"]


@pytest.mark.asyncio
async def test_resolve_phase4_bundle_keeps_global_names_and_reference_slots_separate() -> None:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: Phase1 已确认仍未解析的 slot 列表后，Phase4 不能再把 template 里的已解析 slot 并回 request。
    """
    captured: dict[str, EvidenceRequest] = {}

    class _DummyEvidenceService:
        async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
            captured["request"] = request
            return EvidenceBundle(
                requested_names=list(request.requested_names),
                reference_slots=list(request.reference_slots),
            )

    context = _MultiPhaseExecutionContext(
        client=MagicMock(),
        text="我看着汪淼。",
        chunk_id=3,
        phase4_request_template=EvidenceRequest(
            consumer="annotation_phase4",
            objective="relation",
            query_text="我看着汪淼。",
            requested_names=["我", "她", "汪淼"],
            seed_entities=["我", "她", "汪淼"],
            background_entities=[],
            current_chunk=3,
            max_chunk_id=2,
            exclude_chunk_ids=[3],
            need_level1=True,
            need_level2=True,
            need_level3=False,
            allow_llm_query_expansion=False,
            top_k=5,
            max_queries=3,
            model_rerank_query_max_chars=400,
            reference_slots=["POV_SLOT_C3_我", "LOCAL_REF_C3_她"],
        ),
        evidence_service=_DummyEvidenceService(),
    )

    bundle = await _resolve_phase4_bundle(
        context,
        known_characters=["汪淼"],
        reference_slots=["LOCAL_REF_C3_她"],
        phase1_seen_reference_slots=["POV_SLOT_C3_我", "LOCAL_REF_C3_她"],
    )

    assert captured["request"].requested_names == ["汪淼"]
    assert captured["request"].seed_entities == ["汪淼"]
    assert captured["request"].reference_slots == ["LOCAL_REF_C3_她"]
    assert bundle is not None
    assert bundle.requested_names == ["汪淼"]
    assert bundle.reference_slots == ["LOCAL_REF_C3_她"]


@pytest.mark.asyncio
async def test_run_phase4_from_context_drops_template_slots_already_seen_by_phase1() -> None:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: 当 Phase1 已看见并解析掉 template 里的 slot 时，Phase4 不应再把这些 slot 从 template 回流。
    """
    captured: dict[str, EvidenceRequest] = {}

    class _DummyEvidenceService:
        async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
            captured["request"] = request
            return EvidenceBundle(
                requested_names=list(request.requested_names),
                reference_slots=list(request.reference_slots),
            )

    context = _MultiPhaseExecutionContext(
        client=MagicMock(),
        text="我看着她。",
        chunk_id=3,
        phase4_request_template=EvidenceRequest(
            consumer="annotation_phase4",
            objective="relation",
            query_text="我看着她。",
            requested_names=["我", "她", "汪淼"],
            seed_entities=["我", "她", "汪淼"],
            background_entities=[],
            current_chunk=3,
            max_chunk_id=2,
            exclude_chunk_ids=[3],
            need_level1=True,
            need_level2=True,
            need_level3=False,
            allow_llm_query_expansion=False,
            top_k=5,
            max_queries=3,
            model_rerank_query_max_chars=400,
            reference_slots=["POV_SLOT_C3_我", "LOCAL_REF_C3_她"],
        ),
        evidence_service=_DummyEvidenceService(),
    )

    with patch(
        "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
        new=AsyncMock(return_value=[]),
    ) as mock_phase4:
        await _run_phase4_from_context(
            context,
            known_characters=["汪淼"],
            reference_slots=[],
            phase1_seen_reference_slots=["POV_SLOT_C3_我", "LOCAL_REF_C3_她"],
        )

    assert captured["request"].reference_slots == []
    assert mock_phase4.await_args.kwargs["reference_slots"] == []


@pytest.mark.asyncio
async def test_run_phase4_from_context_keeps_template_reference_slots_when_phase1_slots_empty() -> None:
    """
    创建时间: 2026-04-29
    任务: Phase4 / RAG reference_slots 合同
    新建原因: Phase1 没产出 slot 时，Phase4 仍必须保留 template 里按文本预提的局部引用位。
    """
    captured: dict[str, EvidenceRequest] = {}

    class _DummyEvidenceService:
        async def collect(self, request: EvidenceRequest) -> EvidenceBundle:
            captured["request"] = request
            return EvidenceBundle(
                requested_names=list(request.requested_names),
                reference_slots=list(request.reference_slots),
            )

    context = _MultiPhaseExecutionContext(
        client=MagicMock(),
        text="我看着她。",
        chunk_id=3,
        phase4_request_template=EvidenceRequest(
            consumer="annotation_phase4",
            objective="relation",
            query_text="我看着她。",
            requested_names=["我", "汪淼"],
            seed_entities=["我", "汪淼"],
            background_entities=[],
            current_chunk=3,
            max_chunk_id=2,
            exclude_chunk_ids=[3],
            need_level1=True,
            need_level2=True,
            need_level3=False,
            allow_llm_query_expansion=False,
            top_k=5,
            max_queries=3,
            model_rerank_query_max_chars=400,
            reference_slots=["POV_SLOT_C3_我", "LOCAL_REF_C3_她"],
        ),
        evidence_service=_DummyEvidenceService(),
    )

    with patch(
        "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
        new=AsyncMock(return_value=[]),
    ) as mock_phase4:
        await _run_phase4_from_context(
            context,
            known_characters=["汪淼"],
            reference_slots=[],
        )

    assert captured["request"].reference_slots == ["POV_SLOT_C3_我", "LOCAL_REF_C3_她"]
    assert mock_phase4.await_args.kwargs["reference_slots"] == ["POV_SLOT_C3_我", "LOCAL_REF_C3_她"]
