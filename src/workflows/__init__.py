"""
创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: workflows 模块入口，包含核心业务逻辑，供 API 和 CLI 共同调用
"""

from src.workflows.aggregate import run_aggregate
from src.workflows.annotate import run_annotate
from src.workflows.annotate_helpers.sentence import (
    build_context_sentences,
    build_prev_summary,
    extract_new_names_from_db,
)
from src.workflows.diagnose import (
    build_cloud_payload,
    run_cloud_diagnose,
    run_diagnose,
    run_local_diagnose,
)
from src.workflows.curve_metrics import (
    EVENT_TYPE_SCORES,
    compute_emotion_curve,
    compute_global_stats,
    compute_rhythm_curve,
    compute_tension_signals,
    load_all_lexicons,
)
from src.workflows.preprocess import run_preprocess
from src.workflows.topic import run_topic_model

__all__ = [
    "EVENT_TYPE_SCORES",
    "build_cloud_payload",
    "build_context_sentences",
    "build_prev_summary",
    "compute_emotion_curve",
    "compute_global_stats",
    "compute_rhythm_curve",
    "compute_tension_signals",
    "extract_new_names_from_db",
    "load_all_lexicons",
    "run_aggregate",
    "run_annotate",
    "run_cloud_diagnose",
    "run_diagnose",
    "run_local_diagnose",
    "run_preprocess",
    "run_topic_model",
]
