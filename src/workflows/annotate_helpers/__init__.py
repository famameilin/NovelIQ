"""
创建时间: 2026-03-14
创建者: TraeAI
任务: 解决循环依赖 - 从 cli 提取核心业务逻辑

说明: 本模块从 src.cli.annotate_helpers 迁移而来，用于解决 workflows 与 cli 之间的循环依赖问题。
      所有导入路径已更新为指向 workflows 模块。

本模块将原 annotate_helpers.py 中的函数按功能分类拆分到不同的子模块中。

子模块说明：
- client_init.py: 客户端初始化相关
- context.py: 上下文管理
- disambiguation.py: 消歧相关函数（已拆分为 disambiguation 子包）
- storage.py: 结果存储相关
- phase.py: 阶段管理
- sentence.py: 例句构建相关
"""

from .client_init import (
    _init_annotation_clients,
    _setup_token_usage_callback,
)
from .context import (
    ChunkContext,
    _init_disambig_provider,
    _prepare_chunk_context,
)
from .disambiguation import (
    _run_final_disambiguation_with_state,
    _run_incremental_disambiguation_with_state,
)
from .phase import (
    AnnotationPhaseResult,
    _init_annotation_phase,
    _process_chunks_phase,
    _process_single_chunk,
    _run_disambiguation_phase,
)
from .sentence import (
    _add_identity_clues,
    _annotate_dialogue_structure,
    _build_sentence_pool,
    _extract_and_save_global_context,
)
from .storage import _store_annotation_results

__all__ = [
    "ChunkContext",
    "AnnotationPhaseResult",
    "_init_annotation_clients",
    "_setup_token_usage_callback",
    "_init_disambig_provider",
    "_prepare_chunk_context",
    "_store_annotation_results",
    "_run_incremental_disambiguation_with_state",
    "_run_final_disambiguation_with_state",
    "_init_annotation_phase",
    "_process_single_chunk",
    "_process_chunks_phase",
    "_run_disambiguation_phase",
    "_build_sentence_pool",
    "_annotate_dialogue_structure",
    "_add_identity_clues",
    "_extract_and_save_global_context",
]
