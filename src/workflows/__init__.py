"""
workflows 模块入口，包含核心业务逻辑，供 API 和 CLI 共同调用
"""

from src.config.constants import EVENT_TYPE_SCORES
from src.workflows.aggregate import run_aggregate
from src.workflows.annotate import run_annotate
from src.workflows.curve_metrics import (
    compute_emotion_curve,
    compute_global_stats,
    compute_rhythm_curve,
    compute_tension_signals,
)
from src.workflows.diagnose import (
    run_diagnose,
)
from src.workflows.preprocess import run_preprocess
from src.workflows.topic import run_topic_model

__all__ = [
    "EVENT_TYPE_SCORES",
    "compute_emotion_curve",
    "compute_global_stats",
    "compute_rhythm_curve",
    "compute_tension_signals",
    "run_aggregate",
    "run_annotate",
    "run_diagnose",
    "run_preprocess",
    "run_topic_model",
]
