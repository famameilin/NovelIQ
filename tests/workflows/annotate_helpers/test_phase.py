from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.local.annotation.evidence_renderer import AnnotationPromptBlocks
from src.rag import Level3NotReadyError
from src.workflows.annotate_helpers.context import ChunkContext
from src.workflows.annotate_helpers.phase import (
    AnnotationPhaseConfig,
    _init_annotation_phase_with_config,
    _process_single_chunk,
)


@pytest.mark.asyncio
async def test_process_single_chunk_uses_async_level3_context_builder() -> None:
    next_state = object()
    state = MagicMock()
    state.get_alias_merges_dict.return_value = {"alias": "canonical"}

    phase_result = SimpleNamespace(
        annotation_client=MagicMock(),
        cloud_annotation_client=None,
        incremental_disambig_client=MagicMock(),
        alias_keywords=["称号"],
        global_context_str="global-context",
        evidence_provider=MagicMock(),
        emitter=None,
    )
    context = SimpleNamespace(
        prompt_active_entities="active-entities",
        prompt_disambig_context="vector-evidence",
        evidence_bundle={"structured_evidence": ["authority"]},
    )
    annotation_result = SimpleNamespace(
        annotation={"entities": []},
        foreshadowing=[],
        dialogue_speakers=[],
        dialogues=[],
        dialogue_tones=[],
        dialogue_identity_clues=[],
        relations=[],
    )

    with (
        patch(
            "src.workflows.annotate_helpers.context._prepare_chunk_context_with_level3",
            new=AsyncMock(return_value=context),
        ) as mock_prepare_context,
        patch(
            "src.workflows.annotate_helpers.phase._annotate_chunk",
            new=AsyncMock(return_value=annotation_result),
        ) as mock_annotate_chunk,
        patch("src.workflows.annotate_helpers.storage._store_annotation_results") as mock_store_results,
        patch(
            "src.workflows.annotate_helpers.disambiguation._run_incremental_disambiguation_with_state",
            new=AsyncMock(return_value=next_state),
        ) as mock_run_disambig,
    ):
        result = await _process_single_chunk(
            conn=MagicMock(),
            chunk_id=101,
            chunk_text="当前 chunk 文本",
            idx=0,
            total_chunks=5,
            phase_result=phase_result,
            state=state,
            use_context_enhancement=True,
            incremental_interval=3,
            run_id="run-1",
            novel_id="novel-1",
        )

    assert result is next_state
    mock_prepare_context.assert_awaited_once()
    mock_annotate_chunk.assert_awaited_once()
    assert mock_annotate_chunk.await_args.kwargs["disambig_context"] == "vector-evidence"
    assert mock_annotate_chunk.await_args.kwargs["evidence_bundle"] == {"structured_evidence": ["authority"]}
    mock_store_results.assert_called_once()
    mock_run_disambig.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_single_chunk_prefers_prompt_blocks_over_legacy_strings() -> None:
    next_state = object()
    state = MagicMock()
    state.get_alias_merges_dict.return_value = {"alias": "canonical"}

    phase_result = SimpleNamespace(
        annotation_client=MagicMock(),
        cloud_annotation_client=None,
        incremental_disambig_client=MagicMock(),
        alias_keywords=["称号"],
        global_context_str="global-context",
        evidence_provider=MagicMock(),
        emitter=None,
    )
    context = ChunkContext(
        evidence_bundle=MagicMock(),
        annotation_prompt_blocks=AnnotationPromptBlocks(
            active_entities="BLOCK_ACTIVE",
            disambig_context="BLOCK_DISAMBIG",
        ),
    )
    annotation_result = SimpleNamespace(
        annotation={"entities": []},
        foreshadowing=[],
        dialogue_speakers=[],
        dialogues=[],
        dialogue_tones=[],
        dialogue_identity_clues=[],
        relations=[],
    )

    with (
        patch(
            "src.workflows.annotate_helpers.context._prepare_chunk_context_with_level3",
            new=AsyncMock(return_value=context),
        ) as mock_prepare_context,
        patch(
            "src.workflows.annotate_helpers.phase._annotate_chunk",
            new=AsyncMock(return_value=annotation_result),
        ) as mock_annotate_chunk,
        patch("src.workflows.annotate_helpers.storage._store_annotation_results"),
        patch(
            "src.workflows.annotate_helpers.disambiguation._run_incremental_disambiguation_with_state",
            new=AsyncMock(return_value=next_state),
        ),
    ):
        result = await _process_single_chunk(
            conn=MagicMock(),
            chunk_id=102,
            chunk_text="当前 chunk 文本",
            idx=0,
            total_chunks=5,
            phase_result=phase_result,
            state=state,
            use_context_enhancement=True,
            incremental_interval=3,
            run_id="run-1",
            novel_id="novel-1",
        )

    assert result is next_state
    mock_prepare_context.assert_awaited_once()
    mock_annotate_chunk.assert_awaited_once()
    assert mock_annotate_chunk.await_args.kwargs["active_entities"] == "BLOCK_ACTIVE"
    assert mock_annotate_chunk.await_args.kwargs["disambig_context"] == "BLOCK_DISAMBIG"


@pytest.mark.asyncio
async def test_init_annotation_phase_validates_level3_once_up_front() -> None:
    evidence_provider = MagicMock()
    evidence_provider.ensure_level3_ready = AsyncMock()

    annotation_client = MagicMock()
    cloud_annotation_client = MagicMock()
    incremental_client = MagicMock()
    full_client = MagicMock()

    config = AnnotationPhaseConfig(
        conn=MagicMock(),
        all_chunks=[],
        novel_id="novel-1",
        use_rag=True,
        run_id="run-1",
    )

    with (
        patch(
            "src.workflows.annotate_helpers.client_init._init_annotation_clients",
            return_value=(annotation_client, cloud_annotation_client, incremental_client, full_client),
        ),
        patch("src.workflows.annotate_helpers.client_init._setup_token_usage_callback"),
        patch("src.workflows.annotate_helpers.context._init_evidence_provider", return_value=evidence_provider),
        patch(
            "src.workflows.annotate_helpers.sentence._extract_and_save_global_context",
            new=AsyncMock(return_value="global-context"),
        ),
    ):
        result = await _init_annotation_phase_with_config(config)

    assert result.evidence_provider is evidence_provider
    evidence_provider.ensure_level3_ready.assert_awaited_once()


@pytest.mark.asyncio
async def test_init_annotation_phase_fails_early_when_level3_not_ready() -> None:
    evidence_provider = MagicMock()
    evidence_provider.ensure_level3_ready = AsyncMock(side_effect=Level3NotReadyError("schema missing"))

    annotation_client = MagicMock()
    cloud_annotation_client = MagicMock()
    incremental_client = MagicMock()
    full_client = MagicMock()

    config = AnnotationPhaseConfig(
        conn=MagicMock(),
        all_chunks=[],
        novel_id="novel-1",
        use_rag=True,
        run_id="run-1",
    )

    with (
        patch(
            "src.workflows.annotate_helpers.client_init._init_annotation_clients",
            return_value=(annotation_client, cloud_annotation_client, incremental_client, full_client),
        ),
        patch("src.workflows.annotate_helpers.client_init._setup_token_usage_callback"),
        patch("src.workflows.annotate_helpers.context._init_evidence_provider", return_value=evidence_provider),
        patch(
            "src.workflows.annotate_helpers.sentence._extract_and_save_global_context",
            new=AsyncMock(return_value="global-context"),
        ),
        pytest.raises(Level3NotReadyError, match="schema missing"),
    ):
        await _init_annotation_phase_with_config(config)
