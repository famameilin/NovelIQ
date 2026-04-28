from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.models.events import StreamEvent
from src.config import settings
from src.models.local.annotation.multi_phase import (
    _emit_phase_event,
    _MultiPhaseExecutionContext,
    _resolve_phase4_bundle,
    annotate_chunk_multi_phase,
    annotate_chunk_parallel,
    annotate_chunk_serial,
)
from src.rag.evidence_contracts import EvidenceRequest


def _annotation_result() -> SimpleNamespace:
    return SimpleNamespace(characters=[SimpleNamespace(name="白芷")])


class _PhaseScopedEmitterClient:
    """
    创建时间: 2026-04-28
    任务: fix-annotation-stream-phase-scope
    说明: 用最小可用 client 验证 multi_phase 在并行 phase 下会为流式 thinking/output
    事件补齐显式的 sub_stage/chunk_id，而不是依赖共享 emitter 上下文。
    """

    def __init__(
        self,
        task_type: str = "annotation",
        config: object | None = None,
        client: object | None = None,
        analysis_logger: object | None = None,
        token_usage_callback: object | None = None,
        novel_id: str | None = None,
        session: object | None = None,
    ) -> None:
        self._task_type = task_type
        self._config = config or SimpleNamespace(model="test-model")
        self._client = client or object()
        self._analysis_logger = analysis_logger
        self._token_usage_callback = token_usage_callback
        self._novel_id = novel_id
        self._session = session
        self._emitter = None


@pytest.mark.asyncio
async def test_parallel_multi_phase_keeps_phase3_phase4_evidence_inputs_consistent() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ) as mock_phase3,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ) as mock_phase4,
    ):
        bundle = MagicMock(name="evidence_bundle")
        await annotate_chunk_parallel(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            active_entities="【近期活跃角色】\n- 白芷（other）：观察 [chunk=12]",
            evidence_bundle=bundle,
        )

    assert mock_phase3.await_args.kwargs["evidence_bundle"] is bundle
    assert mock_phase3.await_args.kwargs["active_entities"] == "【近期活跃角色】\n- 白芷（other）：观察 [chunk=12]"
    assert mock_phase4.await_args.kwargs["evidence_bundle"] is bundle


@pytest.mark.asyncio
async def test_parallel_multi_phase_passes_fallback_to_phase3_phase4() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ) as mock_phase3,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ) as mock_phase4,
    ):
        fallback = MagicMock(name="fallback_client")
        await annotate_chunk_parallel(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            fallback_client=fallback,
        )

    assert mock_phase3.await_args.kwargs["fallback_client"] is fallback
    assert mock_phase4.await_args.kwargs["fallback_client"] is fallback


@pytest.mark.asyncio
async def test_serial_multi_phase_keeps_phase3_phase4_evidence_inputs_consistent() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ) as mock_phase3,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ) as mock_phase4,
    ):
        bundle = MagicMock(name="evidence_bundle")
        await annotate_chunk_serial(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            active_entities="【近期活跃角色】\n- 白芷（other）：观察 [chunk=12]",
            evidence_bundle=bundle,
        )

    assert mock_phase3.await_args.kwargs["evidence_bundle"] is bundle
    assert mock_phase3.await_args.kwargs["active_entities"] == "【近期活跃角色】\n- 白芷（other）：观察 [chunk=12]"
    assert mock_phase4.await_args.kwargs["evidence_bundle"] is bundle


@pytest.mark.asyncio
async def test_serial_multi_phase_passes_fallback_to_phase3_phase4() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ) as mock_phase3,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ) as mock_phase4,
    ):
        fallback = MagicMock(name="fallback_client")
        await annotate_chunk_serial(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            fallback_client=fallback,
        )

    assert mock_phase3.await_args.kwargs["fallback_client"] is fallback
    assert mock_phase4.await_args.kwargs["fallback_client"] is fallback


@pytest.mark.asyncio
async def test_annotate_chunk_multi_phase_routes_to_parallel_dispatcher() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_parallel",
            new=AsyncMock(return_value="parallel-result"),
        ) as mock_parallel,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_serial",
            new=AsyncMock(return_value="serial-result"),
        ) as mock_serial,
        patch.object(settings.analysis.multi_phase_annotation, "parallel", True),
    ):
        bundle = MagicMock(name="evidence_bundle")
        fallback = MagicMock(name="fallback_client")
        result = await annotate_chunk_multi_phase(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            chunk_id=12,
            active_entities="【近期活跃角色】\n- 白芷",
            evidence_bundle=bundle,
            fallback_client=fallback,
            run_id="run-1",
            emitter=AsyncMock(),
            disambig_context="上下文",
        )

    assert result == "parallel-result"
    mock_parallel.assert_awaited_once()
    assert mock_parallel.await_args.kwargs["phase1_bundle"] is bundle
    assert mock_parallel.await_args.kwargs["phase2_bundle"] is bundle
    assert mock_parallel.await_args.kwargs["active_entities"] == "【近期活跃角色】\n- 白芷"
    assert mock_parallel.await_args.kwargs["fallback_client"] is fallback
    assert mock_parallel.await_args.kwargs["disambig_context"] == "上下文"
    mock_serial.assert_not_called()


@pytest.mark.asyncio
async def test_annotate_chunk_multi_phase_routes_to_serial_dispatcher() -> None:
    with (
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_parallel",
            new=AsyncMock(return_value="parallel-result"),
        ) as mock_parallel,
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_serial",
            new=AsyncMock(return_value="serial-result"),
        ) as mock_serial,
        patch.object(settings.analysis.multi_phase_annotation, "parallel", False),
    ):
        bundle = MagicMock(name="evidence_bundle")
        fallback = MagicMock(name="fallback_client")
        result = await annotate_chunk_multi_phase(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            chunk_id=12,
            active_entities="【近期活跃角色】\n- 白芷",
            evidence_bundle=bundle,
            fallback_client=fallback,
            run_id="run-1",
            emitter=AsyncMock(),
            disambig_context="上下文",
        )

    assert result == "serial-result"
    mock_serial.assert_awaited_once()
    assert mock_serial.await_args.kwargs["phase1_bundle"] is bundle
    assert mock_serial.await_args.kwargs["phase2_bundle"] is bundle
    assert mock_serial.await_args.kwargs["active_entities"] == "【近期活跃角色】\n- 白芷"
    assert mock_serial.await_args.kwargs["fallback_client"] is fallback
    assert mock_serial.await_args.kwargs["disambig_context"] == "上下文"
    mock_parallel.assert_not_called()


@pytest.mark.asyncio
async def test_parallel_multi_phase_emits_expected_phase_sequence() -> None:
    emitter = AsyncMock()

    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ),
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await annotate_chunk_parallel(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            chunk_id=12,
            emitter=emitter,
        )

    emitted = [
        (call.args[0].action, call.args[0].sub_stage, call.args[0].sub_percent)
        for call in emitter.await_args_list
    ]
    assert emitted == [
        ("start", "phase1", 0),
        ("start", "phase2", 0),
        ("complete", "phase1", 25),
        ("complete", "phase2", 50),
        ("start", "phase3", 50),
        ("start", "phase4", 75),
        ("complete", "phase3", 75),
        ("complete", "phase4", 100),
    ]


@pytest.mark.asyncio
async def test_parallel_multi_phase_stamps_llm_streams_with_explicit_phase_scope() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-annotation-stream-phase-scope
    说明: phase1/phase2 并行时，thinking/output 不能再共用同一个 task 级 sub_stage 上下文；
    每条流事件都必须显式带回自己的 phase 名称和 chunk_id。
    """
    emitted_events: list[StreamEvent] = []

    async def _capture(event: StreamEvent) -> None:
        emitted_events.append(event)

    async def _fake_phase1(client, **_kwargs):
        await client._emitter(StreamEvent(action="thinking", content="phase1-thinking"))
        return _annotation_result()

    async def _fake_phase2(client, **_kwargs):
        await client._emitter(StreamEvent(action="thinking", content="phase2-thinking"))
        return None

    with (
        patch("src.models.local.annotation.multi_phase._run_phase1", new=_fake_phase1),
        patch("src.models.local.annotation.multi_phase._run_phase2", new=_fake_phase2),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ),
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ),
    ):
        client = _PhaseScopedEmitterClient()
        client._emitter = _capture
        await annotate_chunk_parallel(
            client=client,
            text="白芷看向侯飞白。",
            chunk_id=12,
            emitter=_capture,
        )

    thinking_events = [event for event in emitted_events if event.action == "thinking"]
    assert [(event.sub_stage, event.chunk_id, event.content) for event in thinking_events] == [
        ("phase1", 12, "phase1-thinking"),
        ("phase2", 12, "phase2-thinking"),
    ]


@pytest.mark.asyncio
async def test_parallel_phase3_phase4_streams_keep_their_own_scope() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-annotation-stream-phase-scope
    说明: phase3/phase4 会在同一轮 parallel gather 中并发执行；
    若两边的 thinking/output 仍依赖共享 emitter 上下文，前端当前 scope 常会停在最后一次 phase_start 的 phase4，
    从而把 phase3 文本错误并进 phase4。这里锁定两边都必须显式带回各自的 sub_stage/chunk_id。
    """
    emitted_events: list[StreamEvent] = []

    async def _capture(event: StreamEvent) -> None:
        emitted_events.append(event)

    async def _fake_phase3(client, **_kwargs):
        await client._emitter(StreamEvent(action="output", content="phase3-output"))
        await client._emitter(StreamEvent(action="thinking", content="phase3-thinking"))
        return SimpleNamespace(
            dialogue_lengths=None,
            dialogue_speakers=None,
            dialogues=None,
            dialogue_tones=None,
            dialogue_identity_clues=None,
        )

    async def _fake_phase4(client, **_kwargs):
        await client._emitter(StreamEvent(action="output", content="phase4-output"))
        await client._emitter(StreamEvent(action="thinking", content="phase4-thinking"))
        return []

    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch("src.models.local.annotation.multi_phase._run_phase3_if_needed", new=_fake_phase3),
        patch("src.models.local.annotation.multi_phase.annotate_chunk_phase4", new=_fake_phase4),
    ):
        client = _PhaseScopedEmitterClient()
        client._emitter = _capture
        await annotate_chunk_parallel(
            client=client,
            text="白芷看向侯飞白。",
            chunk_id=12,
            emitter=_capture,
        )

    text_events = {
        (event.sub_stage, event.action): (event.chunk_id, event.content)
        for event in emitted_events
        if event.action in {"thinking", "output"}
    }
    assert text_events == {
        ("phase3", "output"): (12, "phase3-output"),
        ("phase3", "thinking"): (12, "phase3-thinking"),
        ("phase4", "output"): (12, "phase4-output"),
        ("phase4", "thinking"): (12, "phase4-thinking"),
    }


@pytest.mark.asyncio
async def test_serial_phase4_streams_keep_phase_scope_after_level3_progress() -> None:
    """
    创建时间: 2026-04-28
    任务: fix-annotation-stream-phase-scope
    说明: 真实故障是 Phase4 先发 start，再跑 Level3 证据准备把进度 sub_stage 改成 level3，
    随后的 phase4 thinking/output 又没显式带 sub_stage，前端就会把它们错误归到 level3 组。
    这里锁定：即便中间存在 level3 进度事件，phase4 自己的流式文本事件仍必须带回 phase4。
    """
    emitted_events: list[StreamEvent] = []

    async def _capture(event: StreamEvent) -> None:
        emitted_events.append(event)

    async def _fake_phase4(client, **_kwargs):
        await _capture(
            StreamEvent(
                action="progress",
                stage="annotate",
                sub_stage="level3",
                chunk_id=12,
                sub_percent=100,
                message="[relation] Level3 证据准备完成",
            )
        )
        await client._emitter(StreamEvent(action="thinking", content="phase4-thinking"))
        await client._emitter(StreamEvent(action="output", content="phase4-output"))
        return []

    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ),
        patch("src.models.local.annotation.multi_phase.annotate_chunk_phase4", new=_fake_phase4),
    ):
        client = _PhaseScopedEmitterClient()
        client._emitter = _capture
        await annotate_chunk_serial(
            client=client,
            text="白芷看向侯飞白。",
            chunk_id=12,
            emitter=_capture,
        )

    text_events = [event for event in emitted_events if event.action in {"thinking", "output"}]
    assert [(event.action, event.sub_stage, event.chunk_id, event.content) for event in text_events] == [
        ("thinking", "phase4", 12, "phase4-thinking"),
        ("output", "phase4", 12, "phase4-output"),
    ]


@pytest.mark.asyncio
async def test_serial_multi_phase_emits_expected_phase_sequence() -> None:
    emitter = AsyncMock()

    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ),
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await annotate_chunk_serial(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            chunk_id=12,
            emitter=emitter,
        )

    emitted = [
        (call.args[0].action, call.args[0].sub_stage, call.args[0].sub_percent)
        for call in emitter.await_args_list
    ]
    assert emitted == [
        ("start", "phase1", 0),
        ("complete", "phase1", 25),
        ("start", "phase2", 25),
        ("complete", "phase2", 50),
        ("start", "phase3", 50),
        ("complete", "phase3", 75),
        ("start", "phase4", 75),
        ("complete", "phase4", 100),
    ]


@pytest.mark.asyncio
async def test_serial_multi_phase_resolves_phase4_bundle_from_known_characters() -> None:
    """
    创建时间: 2026-04-25
    任务: level3-intent-phase-split
    说明: Phase4 relation bundle 应在 Phase1 产出 known_characters 后再取证，不能继续复用 Phase1 identity bundle。
    """
    evidence_service = MagicMock()
    phase4_bundle = MagicMock(name="phase4_bundle")
    evidence_service.collect = AsyncMock(return_value=phase4_bundle)

    with (
        patch(
            "src.models.local.annotation.multi_phase._run_phase1",
            new=AsyncMock(return_value=_annotation_result()),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase2",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.models.local.annotation.multi_phase._run_phase3_if_needed",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    dialogue_lengths=None,
                    dialogue_speakers=None,
                    dialogues=None,
                    dialogue_tones=None,
                    dialogue_identity_clues=None,
                )
            ),
        ),
        patch(
            "src.models.local.annotation.multi_phase.annotate_chunk_phase4",
            new=AsyncMock(return_value=[]),
        ) as mock_phase4,
    ):
        await annotate_chunk_serial(
            client=MagicMock(),
            text="白芷看向侯飞白。",
            phase1_bundle=MagicMock(name="phase1_bundle"),
            phase2_bundle=MagicMock(name="phase2_bundle"),
            phase3_bundle=MagicMock(name="phase3_bundle"),
            phase4_request_template=EvidenceRequest(
                consumer="annotation_phase4",
                objective="relation",
                query_text="白芷看向侯飞白。",
                requested_names=["侯飞白"],
                seed_entities=["侯飞白"],
                background_entities=[],
                current_chunk=12,
                max_chunk_id=11,
                exclude_chunk_ids=[12],
                need_level1=True,
                need_level2=True,
                need_level3=True,
                allow_llm_query_expansion=False,
                top_k=settings.rag.level3_top_k,
                max_queries=settings.rag.level3_max_queries,
                model_rerank_query_max_chars=settings.rag.level3_model_rerank_query_max_chars,
            ),
            evidence_service=evidence_service,
        )

    evidence_service.collect.assert_awaited_once()
    resolved_request = evidence_service.collect.await_args.args[0]
    assert resolved_request.objective == "relation"
    assert resolved_request.requested_names == ["白芷", "侯飞白"]
    assert resolved_request.seed_entities == ["白芷", "侯飞白"]
    assert mock_phase4.await_args.kwargs["evidence_bundle"] is phase4_bundle


@pytest.mark.asyncio
async def test_resolve_phase4_bundle_keeps_seed_entities_out_of_requested_names() -> None:
    """
    创建时间: 2026-04-25
    任务: fix-phase4-request-scope
    说明: Phase4 的 retrieval seed 不能反向扩大 consumer target；
          requested_names 只能来自 known_characters 和模板显式 requested_names。
    """
    evidence_service = MagicMock()
    phase4_bundle = MagicMock(name="phase4_bundle")
    evidence_service.collect = AsyncMock(return_value=phase4_bundle)
    context = _MultiPhaseExecutionContext(
        client=MagicMock(),
        text="白芷看向侯飞白。",
        chunk_id=12,
        phase4_request_template=EvidenceRequest(
            consumer="annotation_phase4",
            objective="relation",
            query_text="白芷看向侯飞白。",
            requested_names=[],
            seed_entities=["旧值"],
            background_entities=[],
            current_chunk=12,
            max_chunk_id=11,
            exclude_chunk_ids=[12],
            need_level1=True,
            need_level2=True,
            need_level3=True,
            allow_llm_query_expansion=False,
            top_k=settings.rag.level3_top_k,
            max_queries=settings.rag.level3_max_queries,
            model_rerank_query_max_chars=settings.rag.level3_model_rerank_query_max_chars,
        ),
        evidence_service=evidence_service,
    )

    resolved_bundle = await _resolve_phase4_bundle(context, known_characters=["白芷"])

    evidence_service.collect.assert_awaited_once()
    resolved_request = evidence_service.collect.await_args.args[0]
    assert resolved_request.requested_names == ["白芷"]
    assert resolved_request.seed_entities == ["白芷", "旧值"]
    assert resolved_bundle is phase4_bundle


@pytest.mark.asyncio
async def test_emit_phase_event_skips_when_emitter_missing() -> None:
    context = _MultiPhaseExecutionContext(
        client=MagicMock(),
        text="白芷看向侯飞白。",
        chunk_id=12,
        emitter=None,
    )

    await _emit_phase_event(
        context,
        action="start",
        phase_name="phase1",
        sub_percent=0,
        message="开始 phase1",
    )
