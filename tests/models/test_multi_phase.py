from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import settings
from src.models.local.annotation.multi_phase import (
    _emit_phase_event,
    _MultiPhaseExecutionContext,
    annotate_chunk_multi_phase,
    annotate_chunk_parallel,
    annotate_chunk_serial,
)
from src.rag.level3_contracts import Level3Request


def _annotation_result() -> SimpleNamespace:
    return SimpleNamespace(characters=[SimpleNamespace(name="白芷")])


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
    evidence_provider = MagicMock()
    phase4_bundle = MagicMock(name="phase4_bundle")
    evidence_provider.collect = AsyncMock(return_value=phase4_bundle)

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
            phase4_request_template=Level3Request(
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
            evidence_provider=evidence_provider,
        )

    evidence_provider.collect.assert_awaited_once()
    resolved_request = evidence_provider.collect.await_args.args[0]
    assert resolved_request.objective == "relation"
    assert resolved_request.requested_names == ["白芷", "侯飞白"]
    assert resolved_request.seed_entities == ["白芷", "侯飞白"]
    assert mock_phase4.await_args.kwargs["evidence_bundle"] is phase4_bundle


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
