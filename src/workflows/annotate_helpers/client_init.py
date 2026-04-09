"""
标注辅助函数模块 - 客户端初始化

创建时间: 2026-03-13
创建者: TraeAI
任务: 项目文件结构整理与拆解

修改历史:
- 2026-03-14: 从 cli.annotate_helpers 迁移，解决循环依赖
- 2026-03-14: 添加 run_id 参数，使用 Repository 模式
- 2026-03-15: 移除向后兼容代码，只使用 Repository 模式
- 2026-04-07: 添加 stream_callback 参数支持（websocket-streaming-progress）

说明: 本模块包含标注相关的客户端初始化函数。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from loguru import logger

from src.config import TaskModelConfig, TaskType, settings
from src.config.analysis_logger import AnalysisLogger
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.disambiguation_types import NameCountCandidate
from src.models.interfaces import AnnotationLike, DisambiguationLike
from src.models.local.disambiguation import ExtendedDisambigResult


class _NoopDisambiguationClient:
    """Fallback disambiguation client for injected lightweight annotation stubs."""

    def __init__(self, config: Any) -> None:
        self._config = config
        self._novel_id: str | None = None
        self._token_usage_callback: Any = None
        self._session: Any = None

    def set_session(self, session: Any) -> None:
        self._session = session

    def set_runtime_context(self, novel_id: str | None, token_usage_callback: Any) -> None:
        self._novel_id = novel_id
        self._token_usage_callback = token_usage_callback

    async def disambiguate_characters(
        self,
        candidates: list[NameCountCandidate],
        context_sentences: dict[str, str] | None = None,
        existing_names: list[str] | None = None,
        rag_hint: str | None = None,
    ) -> ExtendedDisambigResult:
        return ExtendedDisambigResult(canonical_decisions={}, entity_types={}, entity_relations=[])

    def is_cloud_api(self) -> bool:
        return False

    def generate_summary(self, messages: list[dict[str, str]], max_tokens: int = 150) -> str:
        return ""


def _resolve_disambiguation_fallback(
    role: str,
    task_type: TaskType,
    annotation_client: AnnotationLike,
    analysis_logger: AnalysisLogger | None,
) -> DisambiguationLike:
    config = getattr(annotation_client, "_config", None)
    client = getattr(annotation_client, "_client", None)

    if isinstance(annotation_client, DisambiguationLike):
        logger.warning(f"{role} disambiguation config missing, using injected annotation client as fallback")
        return annotation_client

    if isinstance(config, TaskModelConfig):
        try:
            return DisambiguationClient(
                task_type=task_type,
                config=config,
                client=client,
                analysis_logger=analysis_logger,
            )
        except Exception as e:
            logger.warning(
                f"{role} disambiguation fallback from annotation config failed ({e}), using no-op disambiguation client"
            )
    else:
        logger.warning(
            f"{role} disambiguation fallback skipped because "
            f"injected annotation _config is not TaskModelConfig, "
            f"using no-op disambiguation client"
        )

    return _NoopDisambiguationClient(config=config)


def _get_model_name(client: AnnotationLike) -> str:
    """获取模型名称（兼容不同客户端实现）。"""
    config = getattr(client, "_config", None)
    model = getattr(config, "model", None) if config is not None else None
    return model or "unknown"


def _init_annotation_clients(
    analysis_logger: AnalysisLogger | None,
    annotate_client: AnnotationLike | None = None,
    incremental_disambig_client: DisambiguationLike | None = None,
    full_disambig_client: DisambiguationLike | None = None,
    emitter: Callable | None = None,
) -> tuple[AnnotationLike, AnnotationLike | None, DisambiguationLike, DisambiguationLike]:
    """初始化标注客户端
    """
    annotation_client = cast(
        AnnotationLike,
        annotate_client
        or AnnotationClient(task_type="annotation", analysis_logger=analysis_logger),
    )
    # 设置 emitter 到 client，供 multi_phase 内部使用
    if emitter and hasattr(annotation_client, "_emitter"):
        annotation_client._emitter = emitter  # type: ignore[attr-defined]

    cloud_annotation_client: AnnotationLike | None = None
    cloud_fallback_enabled = settings.analysis.cloud_annotation_fallback_enabled

    if cloud_fallback_enabled:
        try:
            cloud_client = AnnotationClient(
                task_type="cloud_annotation", analysis_logger=analysis_logger
            )
            if emitter and hasattr(cloud_client, "_emitter"):
                cloud_client._emitter = emitter  # type: ignore[attr-defined]
            cloud_annotation_client = cast(AnnotationLike, cloud_client)
            logger.info(
                f"cloud annotation client initialized for fallback (thinking={cloud_client._config.thinking_enabled})"
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
            incremental_client = DisambiguationClient(task_type="incremental_disambig", analysis_logger=analysis_logger)
            logger.info("incremental disambiguation client initialized")
        except ValueError as e:
            logger.warning(f"incremental disambiguation config not found, falling back to annotation model: {e}")
            incremental_client = _resolve_disambiguation_fallback(
                role="incremental",
                task_type="incremental_disambig",
                annotation_client=annotation_client,
                analysis_logger=analysis_logger,
            )

    # 全量消歧客户端：如果配置为空，回退到标注模型
    if full_disambig_client:
        full_client = full_disambig_client
    else:
        try:
            full_client = DisambiguationClient(task_type="full_disambig", analysis_logger=analysis_logger)
            logger.info("full disambiguation client initialized")
        except ValueError as e:
            logger.warning(f"full disambiguation config not found, falling back to annotation model: {e}")
            full_client = _resolve_disambiguation_fallback(
                role="full",
                task_type="full_disambig",
                annotation_client=annotation_client,
                analysis_logger=analysis_logger,
            )

    return annotation_client, cloud_annotation_client, incremental_client, full_client


def _setup_token_usage_callback(
    conn,
    clients: list,
    novel_id: str,
    annotation_client: AnnotationLike,
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
                _get_model_name(annotation_client),
                prompt_tokens,
                total_tokens,
                completion_tokens,
                chunk_id,
            )
        except Exception as e:
            logger.warning(f"failed to record token usage: {e}")

    for client in clients:
        if client is not None:
            client.set_runtime_context(novel_id, _token_usage_callback)
