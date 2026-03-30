"""
标注辅助函数模块 - 消歧处理

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式
- 2026-03-16: 增量消歧只维护内存 alias_map，添加 checkpoint 机制
- 2026-03-20: 移除硬编码的 VALID_HIERARCHICAL_RELATION_TYPES，改为从配置动态读取
- 2026-03-26: 添加置信度校验逻辑，根据证据来源约束置信度输出
- 2026-03-27: 拆分为多个子模块

说明: 本模块已拆分为 disambiguation 子包，此文件仅作为兼容层转发导入。
"""

from .disambiguation import (
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_LOW,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_STATE_RESOLVED,
    DISAMBIG_STATE_REVIEW,
    DISAMBIG_STATE_UNRESOLVED,
    EXTENSION_REVIEW_MIN_GAP,
    EXTENSION_REVIEW_MIN_RATIO,
    VALID_DISAMBIG_CONFIDENCE,
    DisambigStateSnapshot,
    DisambiguationMaxRetriesExceededError,
    _load_disambig_checkpoint,
    _process_entity_relations,
    _run_final_disambiguation_with_state,
    _run_incremental_disambiguation_with_state,
    _save_disambig_checkpoint,
    apply_disambiguation_decisions,
    detect_cycle_in_relations,
    extract_new_names_from_db,
    validate_confidence_with_evidence,
)

__all__ = [
    "apply_disambiguation_decisions",
    "validate_confidence_with_evidence",
    "_run_incremental_disambiguation_with_state",
    "_run_final_disambiguation_with_state",
    "extract_new_names_from_db",
    "detect_cycle_in_relations",
    "_process_entity_relations",
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
