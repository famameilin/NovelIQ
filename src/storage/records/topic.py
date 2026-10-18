"主题模型实际构建记录"

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TopicModelRunContract:
    "主题模型读取模型（attribute 面与旧契约一致，来源改为 analysis_runs.lda_*）"

    run_id: str
    library_version: str
    pipeline_version: str
    num_topics: int
    passes: int
    iterations: int
    alpha: float
    eta: float
    random_state: int
    lda_batch_size: int
    minimum_probability: float
    dictionary_size: int
    training_document_count: int
    inference_paragraph_count: int
    artifact_key: str
    created_at: datetime | None = None
