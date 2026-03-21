"""
创建时间: 2025-03-11
创建者: TraeAI
任务: 模型客户端统一封装

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 处理云端 API 返回字符串而非 ChatCompletion 对象的情况

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 云端API不支持top_k参数，移除extra_body中的top_k以避免请求失败

修改时间: 2026-03-11
修改者: TraeAI
修改内容: 将云端模型相关日志提升为info等级，添加prompt和返回内容的控制台打印

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 修复标注阶段JSON解析失败时静默返回空结果导致任务状态错误标记为completed的问题
- 当JSON解析失败时抛出ValueError异常而非静默返回空ChunkAnnotation
- 这样可以让上层正确捕获异常并将任务标记为failed

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 项目文件结构整理与拆解
- 将标注功能委托给 AnnotationClient
- 将消歧功能委托给 DisambiguationClient

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 添加私有方法代理

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 修复 token_usage_stats 统计为空的问题
- 问题原因：外部设置 _token_usage_callback 和 _novel_id 时，只设置了 UnifiedModelClient 自身的属性，
  没有同步到内部的 _annotation_client 和 _disambiguation_client
- 解决方案：将 _token_usage_callback 和 _novel_id 改为 property，setter 时自动同步到内部客户端

修改时间: 2026-03-17
修改者: TraeAI
修改内容: 修复导入错误
- 问题原因: TwoPhaseAnnotationResult 定义在 annotation_client.py，但从 schema.py 导入
- 解决方案: 从 annotation_client 导入 TwoPhaseAnnotationResult

修改时间: 2026-03-18
修改者: TraeAI
任务: entity-type-relation-extraction
修改内容: disambiguate_characters 方法返回 ExtendedDisambigResult 类型
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.config import TaskModelConfig, TaskType
from src.config.analysis_logger import AnalysisLogger

from .annotation_client import AnnotationClient, TwoPhaseAnnotationResult
from .base import TokenUsageCallback
from .disambiguation import ExtendedDisambigResult
from .disambiguation_client import DisambiguationClient
from .schema import ChunkAnnotation

if TYPE_CHECKING:
    from .annotation_client import AnnotationClient as AnnotationClientType


class UnifiedModelClient:
    """
    统一模型客户端，根据任务类型加载配置

    组合使用 AnnotationClient 和 DisambiguationClient 提供完整功能。
    """

    def __init__(
        self,
        task_type: TaskType,
        config: TaskModelConfig | None = None,
        client: Any | None = None,
        analysis_logger: AnalysisLogger | None = None,
        token_usage_callback: Optional[TokenUsageCallback] = None,
        novel_id: Optional[str] = None,
        instructor_client_factory: Optional[Any] = None,
        session: Optional[Any] = None,
    ) -> None:
        """
        修改时间: 2026-03-16
        修改者: TraeAI
        任务: 支持依赖注入 instructor_client_factory，便于测试

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 支持传入 session 用于保存模型交互记录
        修改内容: 添加 session 参数，传递给 AnnotationClient 和 DisambiguationClient
        """
        self._task_type = task_type
        self._annotation_client = AnnotationClient(
            task_type=task_type,
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            instructor_client_factory=instructor_client_factory,
            session=session,
        )
        self._disambiguation_client = DisambiguationClient(
            task_type=task_type if task_type in ("incremental_disambig", "full_disambig") else "incremental_disambig",
            config=config,
            client=client,
            analysis_logger=analysis_logger,
            token_usage_callback=token_usage_callback,
            novel_id=novel_id,
            instructor_client_factory=instructor_client_factory,
            session=session,
        )

        self._config = self._annotation_client._config
        self._analysis_logger = analysis_logger
        self.__dict__["_token_usage_callback_value"] = token_usage_callback
        self.__dict__["_novel_id_value"] = novel_id

    @property
    def _client(self):
        return self._annotation_client._client

    @property
    def _token_usage_callback(self):
        return self.__dict__.get("_token_usage_callback_value")

    @_token_usage_callback.setter
    def _token_usage_callback(self, value):
        self.__dict__["_token_usage_callback_value"] = value
        self._annotation_client._token_usage_callback = value
        self._disambiguation_client._token_usage_callback = value

    @property
    def _novel_id(self):
        return self.__dict__.get("_novel_id_value")

    @_novel_id.setter
    def _novel_id(self, value):
        self.__dict__["_novel_id_value"] = value
        self._annotation_client._novel_id = value
        self._disambiguation_client._novel_id = value

    def annotate_chunk(
        self,
        text: str,
        prev_summary: str | None = None,
        alias_map: Dict[str, str] | None = None,
        chunk_id: int | None = None,
        global_context: str | None = None,
        prev_chunk_text: str | None = None,
        active_entities: str | None = None,
        rag_evidence: str | None = None,
        known_aliases: str | None = None,
        next_chunk_text: str | None = None,
        cloud_client: "UnifiedModelClient | None" = None,
        run_id: str | None = None,
    ) -> "TwoPhaseAnnotationResult":
        """
        对文本块进行语义标注

        修改时间: 2026-03-19
        修改者: TraeAI
        任务: 统一字段命名，使用 prev_chunk_text 和 next_chunk_text，添加 run_id 支持
        """
        internal_cloud_client: AnnotationClientType | None = None
        if cloud_client is not None:
            internal_cloud_client = cloud_client._annotation_client
        return self._annotation_client.annotate_chunk(
            text=text,
            prev_summary=prev_summary,
            alias_map=alias_map,
            chunk_id=chunk_id,
            global_context=global_context,
            prev_chunk_text=prev_chunk_text,
            active_entities=active_entities,
            rag_evidence=rag_evidence,
            known_aliases=known_aliases,
            next_chunk_text=next_chunk_text,
            cloud_client=internal_cloud_client,
            run_id=run_id,
        )

    def disambiguate_characters(
        self,
        candidates: List[str] | List[Dict[str, int]],
        context_sentences: Dict[str, str] | None = None,
        existing_names: List[str] | None = None,
        rag_hint: str | None = None,
    ) -> ExtendedDisambigResult:
        """
        人名消歧

        修改时间: 2026-03-18
        修改者: TraeAI
        任务: entity-type-relation-extraction
        修改内容: 返回 ExtendedDisambigResult 类型，包含 entity_types 和 entity_relations
        """
        return self._disambiguation_client.disambiguate_characters(
            candidates=candidates,
            context_sentences=context_sentences,
            existing_names=existing_names,
            rag_hint=rag_hint,
        )

    def disambiguate_anonymous(
        self,
        anonymous_names: List[str],
        anonymous_contexts: Dict[str, str],
        existing_names: List[str] | None = None,
        existing_contexts: Dict[str, str] | None = None,
    ) -> Dict[str, str]:
        return self._disambiguation_client.disambiguate_anonymous(
            anonymous_names=anonymous_names,
            anonymous_contexts=anonymous_contexts,
            existing_names=existing_names,
            existing_contexts=existing_contexts,
        )

    def _parse_annotation(self, content: str) -> ChunkAnnotation:
        """代理到 AnnotationClient._parse_annotation"""
        return self._annotation_client._parse_annotation(content)

    def _parse_active_entities(self, active_entities: str | None) -> list[str]:
        """解析活跃实体字符串"""
        from src.models.local.parser import parse_active_entities

        return parse_active_entities(active_entities)

    def _build_anonymous_disambig_messages(
        self,
        anonymous_names: List[str],
        anonymous_contexts: Dict[str, str],
        existing_names: List[str] | None = None,
        existing_contexts: Dict[str, str] | None = None,
    ) -> List[Dict[str, str]]:
        """构建匿名消歧消息"""
        from src.models.local.disambiguation import build_anonymous_disambig_messages

        return build_anonymous_disambig_messages(
            anonymous_names=anonymous_names,
            anonymous_contexts=anonymous_contexts,
            existing_names=existing_names,
            existing_contexts=existing_contexts,
        )


__all__ = [
    "UnifiedModelClient",
    "TokenUsageCallback",
]
