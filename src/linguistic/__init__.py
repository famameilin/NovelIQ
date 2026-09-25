"""语言结构基础数据链路（《分析能力扩展路线图》赛道 B/C）
"""

from __future__ import annotations

from .emotion_boundary import (
    EmotionBoundary,
    fit_emotion_boundary,
    score_items,
    strong_negative_share,
)
from .emotion_events import EmotionEvent, extract_emotion_events, mneg_corrected_counts
from .ltp_client import LtpSession, analyze_paragraph, analyze_paragraph_batch
from .phrase_matcher import PhraseMatch, match_fixed_phrases
from .schema import (
    LtpDependencyArc,
    LtpEntityCandidate,
    LtpSdpArc,
    LtpToken,
    ParagraphLinguisticResult,
)
from .word2vec import (
    PosEmbeddingRow,
    TrainResult,
    build_pos_embeddings,
    load_shared_pretrained_vectors,
    reset_pretrained_cache,
    resolve_shared_pretrained_path,
    train_book_model,
)

__all__ = [
    "EmotionEvent",
    "EmotionBoundary",
    "LtpDependencyArc",
    "LtpEntityCandidate",
    "LtpSdpArc",
    "LtpSession",
    "LtpToken",
    "ParagraphLinguisticResult",
    "PhraseMatch",
    "PosEmbeddingRow",
    "TrainResult",
    "analyze_paragraph",
    "analyze_paragraph_batch",
    "build_pos_embeddings",
    "extract_emotion_events",
    "fit_emotion_boundary",
    "load_shared_pretrained_vectors",
    "match_fixed_phrases",
    "mneg_corrected_counts",
    "resolve_shared_pretrained_path",
    "reset_pretrained_cache",
    "score_items",
    "strong_negative_share",
    "train_book_model",
]
