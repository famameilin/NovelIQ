"""
标注命令行入口

创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: 此文件为 CLI 薄层，核心业务逻辑委托给 src.workflows 模块
"""

from __future__ import annotations

from src.workflows.annotate import run_annotate
from src.workflows.annotate_helpers.disambiguation import (
    DisambiguationMaxRetriesExceededError,
    _retry_disambig,
)
from src.workflows.annotate_helpers.phase import (
    ChunkAnnotationMaxRetriesExceededError,
    _annotate_chunk,
)
from src.workflows.annotate_helpers.sentence import (
    annotate_dialogue_structure,
    build_context_sentences,
    build_prev_summary,
    compute_dialogue_lengths,
    extract_new_names_from_db,
    extract_speaker_from_sentence,
)
from src.workflows.retry_utils import MaxRetriesExceededError, RetryableOperation

__all__ = [
    "ChunkAnnotationMaxRetriesExceededError",
    "DisambiguationMaxRetriesExceededError",
    "MaxRetriesExceededError",
    "RetryableOperation",
    "_annotate_chunk",
    "_retry_disambig",
    "annotate_dialogue_structure",
    "build_context_sentences",
    "build_prev_summary",
    "compute_dialogue_lengths",
    "extract_new_names_from_db",
    "extract_speaker_from_sentence",
    "run_annotate",
]
