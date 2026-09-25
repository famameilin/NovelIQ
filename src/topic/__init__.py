from __future__ import annotations

from .lda_model import (
    LDAConfig,
    LDATrainer,
    get_all_topic_words,
    get_topic_words,
    infer_document_topics,
    infer_paragraph_topics,
)
from .preprocessor import TopicPreprocessor
from .schema import (
    INFERENCE_COMPLETE,
    INFERENCE_EMPTY_AFTER_PREPROCESS,
    INFERENCE_EMPTY_BOW,
    INFERENCE_FAILED,
    ParagraphInferenceResult,
    TopicModel,
    TopicResult,
    TopicWord,
)

#: 主题预处理与推断管线版本（topic_model_runs.pipeline_version，§5.8）
#: 完整 K 维落库 + 段落推断状态 + 模型契约表的首个版本
TOPIC_PIPELINE_VERSION = "1.0"

__all__ = [
    "INFERENCE_COMPLETE",
    "INFERENCE_EMPTY_AFTER_PREPROCESS",
    "INFERENCE_EMPTY_BOW",
    "INFERENCE_FAILED",
    "ParagraphInferenceResult",
    "TOPIC_PIPELINE_VERSION",
    "LDAConfig",
    "LDATrainer",
    "TopicModel",
    "TopicPreprocessor",
    "TopicResult",
    "TopicWord",
    "infer_document_topics",
    "infer_paragraph_topics",
    "get_topic_words",
    "get_all_topic_words",
]