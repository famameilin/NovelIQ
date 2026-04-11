from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflows.annotate_helpers.phase import _process_single_chunk


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
        rag_retriever=MagicMock(),
        emitter=None,
    )
    context = SimpleNamespace(
        active_entities_str="active-entities",
        disambig_context_str="vector-evidence",
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
    mock_store_results.assert_called_once()
    mock_run_disambig.assert_awaited_once()
