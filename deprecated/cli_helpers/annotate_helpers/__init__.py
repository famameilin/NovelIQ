"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块将原 annotate_helpers.py 中的函数按功能分类拆分到不同的子模块中。

子模块说明：
- client_init.py: 客户端初始化相关
- context.py: 上下文管理
- disambiguation.py: 消歧相关函数
- storage.py: 结果存储相关
- phase.py: 阶段管理
- sentence.py: 例句构建相关
"""

from src.models.local.unified_client import UnifiedModelClient

from .client_init import (
    _init_annotation_clients,
    _setup_token_usage_callback,
)
from .context import (
    ChunkContext,
    _init_rag_retriever,
    _prepare_chunk_context,
)
from .disambiguation import (
    _build_character_knowledge_graph,
    _run_anonymous_disambiguation,
    _run_final_disambiguation,
    _run_incremental_disambiguation,
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
    _add_prev_summaries,
    _annotate_dialogue_structure,
    _build_sentence_pool,
    _extract_and_save_global_context,
    _load_alias_keywords,
)
from .storage import _store_annotation_results

__all__ = [
    "UnifiedModelClient",
    "ChunkContext",
    "AnnotationPhaseResult",
    "_init_annotation_clients",
    "_setup_token_usage_callback",
    "_init_rag_retriever",
    "_prepare_chunk_context",
    "_store_annotation_results",
    "_run_incremental_disambiguation",
    "_run_final_disambiguation",
    "_run_anonymous_disambiguation",
    "_build_character_knowledge_graph",
    "_init_annotation_phase",
    "_process_single_chunk",
    "_process_chunks_phase",
    "_run_disambiguation_phase",
    "_build_sentence_pool",
    "_annotate_dialogue_structure",
    "_add_prev_summaries",
    "_add_identity_clues",
    "_load_alias_keywords",
    "_extract_and_save_global_context",
]
