"""
消歧模块

创建时间: 2026-03-27
创建者: TraeAI
任务: disambiguation-module-split
说明: 从 disambiguation.py 拆分为多个子模块

子模块说明：
- state_logic.py: 状态决策和校验逻辑
- checkpoint.py: 检查点保存和加载
- candidates.py: 候选名字收集和筛选
- relations.py: 关系处理逻辑
- pipeline.py: 主流程编排
"""

from .candidates import (
    EXTENSION_REVIEW_MIN_GAP,
    EXTENSION_REVIEW_MIN_RATIO,
    DisambigStateSnapshot,
    _collect_final_disambiguation_candidates,
    extract_new_names_from_db,
)
from .checkpoint import (
    _load_disambig_checkpoint,
    _save_disambig_checkpoint,
)
from .pipeline import (
    DisambiguationMaxRetriesExceededError,
    _retry_disambig,
    _run_final_disambiguation_with_state,
    _run_incremental_disambiguation_with_state,
)
from .relations import (
    _extract_retryable_relations,
    _is_valid_inverse_pair,
    _process_entity_relations,
    detect_cycle_in_relations,
)
from .state_logic import (
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_LOW,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_STATE_RESOLVED,
    DISAMBIG_STATE_REVIEW,
    DISAMBIG_STATE_UNRESOLVED,
    VALID_DISAMBIG_CONFIDENCE,
    apply_disambiguation_decisions,
    validate_confidence_with_evidence,
)

__all__ = [
    "apply_disambiguation_decisions",
    "validate_confidence_with_evidence",
    "_run_incremental_disambiguation_with_state",
    "_run_final_disambiguation_with_state",
    "_retry_disambig",
    "extract_new_names_from_db",
    "detect_cycle_in_relations",
    "_is_valid_inverse_pair",
    "_process_entity_relations",
    "_extract_retryable_relations",
    "_collect_final_disambiguation_candidates",
    "DisambiguationMaxRetriesExceededError",
    "DISAMBIG_CONFIDENCE_LOW",
    "DISAMBIG_CONFIDENCE_MEDIUM",
    "DISAMBIG_CONFIDENCE_HIGH",
    "VALID_DISAMBIG_CONFIDENCE",
    "DISAMBIG_STATE_RESOLVED",
    "DISAMBIG_STATE_REVIEW",
    "DISAMBIG_STATE_UNRESOLVED",
    "EXTENSION_REVIEW_MIN_GAP",
    "EXTENSION_REVIEW_MIN_RATIO",
    "_save_disambig_checkpoint",
    "_load_disambig_checkpoint",
    "DisambigStateSnapshot",
]
