from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.annotation.multi_phase import annotate_chunk_parallel, annotate_chunk_serial


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
