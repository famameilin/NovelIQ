"""
说明: annotation 子模块初始化
"""

from __future__ import annotations

from src.models.local.annotation.api_call import (
    execute_validation_retry_call,
    extract_names_from_annotation,
    log_annotation_start,
    parse_annotation,
    should_use_stream,
    validate_annotation,
)
from src.models.local.annotation.context import (
    AnnotationContext,
    MultiPhaseAnnotationResult,
    NameValidationMaxRetriesExceededError,
    Phase1MaxRetriesExceededError,
    Phase2MaxRetriesExceededError,
)
from src.models.local.annotation.evidence_renderer import (
    AnnotationPromptBlocks,
    render_annotation_prompt_blocks,
)
from src.models.local.annotation.messages import (
    _build_annotation_messages_v2,
    _build_foreshadowing_messages,
)
from src.models.local.annotation.phase3 import (
    DialogueLengthResult,
    attribute_dialogues_with_llm,
    compute_dialogue_lengths_with_llm,
    extract_dialogues_from_text,
)
from src.models.local.annotation.phase4 import annotate_chunk_phase4
from src.models.local.annotation.phases import (
    build_phase1_messages,
    build_phase2_messages,
    build_validation_sources,
)
from src.models.local.annotation.response import (
    log_annotation_result,
    log_prompt_response,
    process_annotation_response,
)
from src.models.local.annotation.validation import (
    retry_with_validation,
    validate_annotation_names,
)
from src.models.local.evidence_renderer_shared import render_vector_evidence

__all__ = [
    "AnnotationContext",
    "NameValidationMaxRetriesExceededError",
    "Phase1MaxRetriesExceededError",
    "Phase2MaxRetriesExceededError",
    "MultiPhaseAnnotationResult",
    "AnnotationPromptBlocks",
    "DialogueLengthResult",
    "render_annotation_prompt_blocks",
    "render_vector_evidence",
    "_build_annotation_messages_v2",
    "_build_foreshadowing_messages",
    "build_phase1_messages",
    "build_phase2_messages",
    "build_validation_sources",
    "process_annotation_response",
    "log_prompt_response",
    "log_annotation_result",
    "validate_annotation_names",
    "retry_with_validation",
    "parse_annotation",
    "extract_names_from_annotation",
    "execute_validation_retry_call",
    "validate_annotation",
    "log_annotation_start",
    "should_use_stream",
    "attribute_dialogues_with_llm",
    "compute_dialogue_lengths_with_llm",
    "extract_dialogues_from_text",
    "annotate_chunk_phase4",
]
