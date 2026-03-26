"""
创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 标注辅助函数模块

本模块包含标注相关的客户端初始化函数。
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
) -> Tuple[UnifiedModelClient, UnifiedModelClient | None, UnifiedModelClient, UnifiedModelClient]:
    """
    初始化标注客户端

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责初始化本地和云端标注客户端

    Returns:
        Tuple: (annotation_client, cloud_annotation_client, incremental_disambig_client, full_disambig_client)
    """
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

    incremental_disambig_client = UnifiedModelClient("incremental_disambig", analysis_logger=analysis_logger)
    full_disambig_client = UnifiedModelClient("full_disambig", analysis_logger=analysis_logger)

    return annotation_client, cloud_annotation_client, incremental_disambig_client, full_disambig_client


def _setup_token_usage_callback(
    conn,
    clients: list,
    novel_id: str,
    annotation_client: UnifiedModelClient,
) -> None:
    """
    设置token使用回调

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_annotate 中提取，负责设置token使用记录回调
    """
    from src.storage.operations import insert_token_usage

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
            insert_token_usage(
                conn,
                novel_id=cb_novel_id,
                task_type=task_type,
                call_type=call_type,
                model=annotation_client._config.model or "unknown",
                prompt_tokens=prompt_tokens,
                total_tokens=total_tokens,
                completion_tokens=completion_tokens,
                chunk_id=chunk_id,
            )
        except Exception as e:
            logger.warning(f"failed to record token usage: {e}")

    for client in clients:
        if client is not None:
            client._token_usage_callback = _token_usage_callback
            client._novel_id = novel_id
