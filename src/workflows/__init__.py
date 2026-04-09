"""
创建时间: 2026-03-14
创建者: TraeAI
任务: refactor-module-coupling
说明: workflows 模块入口，包含核心业务逻辑，供 API 和 CLI 共同调用

修改时间: 2026-03-28
修改者: TraeAI
任务: consolidate-codebase-architecture
修改内容: EVENT_TYPE_SCORES 改为从 src.config.constants 导入

修改时间: 2026-04-08
修改者: TraeAI
任务: 移除未使用的 build_cloud_payload 和 run_cloud_diagnose
修改内容: 移除相关导入和导出
"""

from src.config.constants import EVENT_TYPE_SCORES
from src.workflows.aggregate import run_aggregate
from src.workflows.annotate import run_annotate
from src.workflows.annotate_helpers.sentence import (
    build_context_sentences,
)
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
    "build_context_sentences",
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
