"""段落指标批量计算：段数达到阈值时按进程池并行，结果顺序与输入一致。"""

from __future__ import annotations

import os
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from src.metrics.paragraph_metrics import ParagraphMetricCounts, compute_paragraph_metric_counts
from src.text_processing.tokenize import tokenize

#: 单个子进程一次处理的段数，块大一些摊薄进程间传参开销
CHUNK_SIZE = 250

#: 低于该段数走单进程，进程启动开销超过并行收益
PARALLEL_MIN_PARAGRAPHS = 2000

_LEXICONS: dict[str, Any] | None = None


def parallel_worker_count() -> int:
    """并行进程数：按逻辑核数折半近似物理核数"""
    return max(1, (os.cpu_count() or 2) // 2)


def _init_lexicons(lexicons: dict[str, Any]) -> None:
    global _LEXICONS
    _LEXICONS = lexicons


def _count_chunk(texts: list[str]) -> list[ParagraphMetricCounts]:
    lexicons = _LEXICONS
    if lexicons is None:
        raise RuntimeError("段落指标子进程未收到词表")
    return [compute_paragraph_metric_counts(text, tokenize(text), lexicons) for text in texts]


def compute_paragraph_metric_counts_many(
    texts: Sequence[str],
    tokenized: Sequence[list[str]],
    lexicons: dict[str, Any],
    workers: int | None = None,
) -> list[ParagraphMetricCounts]:
    """计算一组段落的指标

    tokenized 供单进程路径复用已分词结果；并行路径在子进程内分词，只传原文。
    """
    worker_count = workers if workers is not None else parallel_worker_count()
    if len(texts) < PARALLEL_MIN_PARAGRAPHS or worker_count <= 1:
        return [
            compute_paragraph_metric_counts(text, tokens, lexicons)
            for text, tokens in zip(texts, tokenized, strict=True)
        ]
    plain_texts = list(texts)
    chunks = [plain_texts[start : start + CHUNK_SIZE] for start in range(0, len(plain_texts), CHUNK_SIZE)]
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_init_lexicons,
        initargs=(lexicons,),
    ) as executor:
        chunk_results = list(executor.map(_count_chunk, chunks))
    return [counts for chunk in chunk_results for counts in chunk]
