"""
标注辅助函数模块 - 客户端初始化

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式

说明: 本模块包含标注相关的客户端初始化函数。
"""

from __future__ import annotations

from typing import Tuple

from loguru import logger

from src.config import settings
from src.config.analysis_logger import AnalysisLogger
from src.models.local.unified_client import UnifiedModelClient


def _init_annotation_clients(
    analysis_logger: AnalysisLogger | None,
    annotate_client: UnifiedModelClient | None = None,
    incremental_disambig_client: UnifiedModelClient | None = None,
    full_disambig_client: UnifiedModelClient | None = None,
) -> Tuple[UnifiedModelClient, UnifiedModelClient | None, UnifiedModelClient, UnifiedModelClient]:
    """初始化标注客户端"""
    annotation_client = annotate_client or UnifiedModelClient("annotation", analysis_logger=analysis_logger)

    cloud_annotation_client: UnifiedModelClient | None = None
    cloud_fallback_enabled = settings.analysis.cloud_annotation_fallback_enabled

    if cloud_fallback_enabled:
        try:
            cloud_annotation_client = UnifiedModelClient("cloud_annotation", analysis_logger=analysis_logger)
            logger.info(
                f"cloud annotation client initialized for fallback (thinking={cloud_annotation_client._config.thinking_enabled})"
            )
        except Exception as e:
            logger.warning(f"cloud annotation client initialization failed, fallback disabled: {e}")
    else:
        logger.info("cloud annotation fallback is disabled by config")

    # 增量消歧客户端：如果配置为空，回退到标注模型
    if incremental_disambig_client:
        incremental_client = incremental_disambig_client
    else:
        try:
            incremental_client = UnifiedModelClient("incremental_disambig", analysis_logger=analysis_logger)
            logger.info("incremental disambiguation client initialized")
        except ValueError as e:
            logger.warning(f"incremental disambiguation config not found, falling back to annotation model: {e}")
            incremental_client = annotation_client

    # 全量消歧客户端：如果配置为空，回退到标注模型
    if full_disambig_client:
        full_client = full_disambig_client
    else:
        try:
            full_client = UnifiedModelClient("full_disambig", analysis_logger=analysis_logger)
            logger.info("full disambiguation client initialized")
        except ValueError as e:
            logger.warning(f"full disambiguation config not found, falling back to annotation model: {e}")
            full_client = annotation_client

    return annotation_client, cloud_annotation_client, incremental_client, full_client


def _setup_token_usage_callback(
    conn,
    clients: list,
    novel_id: str,
    annotation_client: UnifiedModelClient,
    run_id: str,
) -> None:
    """设置token使用回调"""
    from src.storage.repositories import StatsRepository

    def _token_usage_callback(
        cb_novel_id: str,
        task_type: str,
        call_type: str,
        prompt_tokens: int,
        total_tokens: int,
        completion_tokens: int | None,
        chunk_id: int | None,
    ) -> None:
        try:
            stats_repo = StatsRepository(conn)
            stats_repo.insert_token_usage(
                run_id,
                cb_novel_id,
                task_type,
                call_type,
                annotation_client._config.model or "unknown",
                prompt_tokens,
                total_tokens,
                completion_tokens,
                chunk_id,
            )
        except Exception as e:
            logger.warning(f"failed to record token usage: {e}")

    for client in clients:
        if client is not None:
            client._token_usage_callback = _token_usage_callback
            client._novel_id = novel_id
