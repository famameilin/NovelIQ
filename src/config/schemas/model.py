"""
创建时间: 2026-03-12
创建者: TraeAI
任务: 项目文件结构整理与拆解 - 从 settings.py 拆分模型相关配置类

本模块包含模型相关的配置数据类。

修改时间: 2026-03-12
修改者: TraeAI
修改内容: 将thinking配置从各模型配置中移出，统一到独立的thinking配置块

修改时间: 2026-03-16
修改者: TraeAI
修改内容: 支持从环境变量读取模型配置，敏感信息不再硬编码在 settings.json

修改时间: 2026-04-20
修改者: Codex
任务: 清理无效模型配置项
修改内容: 删除 provider 和模型级 max_retries 配置，避免暴露未生效的伪配置入口

修改时间: 2026-04-20
修改者: Codex
任务: refactor-role-based-model-client-names
修改内容: 将 cloud_annotation 重命名为 annotation_fallback，明确它表达的是标注兜底角色而非部署位置
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThinkingConfig:
    """任务级思考模式配置"""

    enabled: bool = False
    budget_tokens: int | None = None


@dataclass
class TaskModelSettings:
    """
    任务模型配置（不包含thinking，thinking统一在顶层配置）

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 移除 backend_name 字段，迁移到 OpenAI SDK 后不再需要区分后端
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    presence_penalty: float = 1.5


@dataclass
class EmbeddingModelSettings:
    """嵌入模型配置"""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    embedding_dim: int = 1536
    batch_size: int = 8


@dataclass
class ModelsSettings:
    """
    任务级模型配置集合

    修改时间: 2026-04-20
    修改者: Codex
    任务: refactor-role-based-model-client-names
    修改内容: 将 cloud_annotation 重命名为 annotation_fallback，避免把客户端角色误命名为 provider
    """

    annotation: TaskModelSettings = field(default_factory=TaskModelSettings)
    annotation_fallback: TaskModelSettings = field(default_factory=TaskModelSettings)
    incremental_disambig: TaskModelSettings = field(default_factory=TaskModelSettings)
    mention_extraction: TaskModelSettings = field(default_factory=TaskModelSettings)
    semantic_chunking: EmbeddingModelSettings = field(default_factory=EmbeddingModelSettings)
    full_disambig: TaskModelSettings = field(default_factory=TaskModelSettings)
    level3_rerank: TaskModelSettings = field(default_factory=TaskModelSettings)
    diagnosis: TaskModelSettings = field(default_factory=TaskModelSettings)


@dataclass
class ThinkingSettings:
    """
    各任务thinking开关配置

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: 将thinking配置从各模型配置中独立出来

    修改时间: 2026-04-09
    创建者: TraeAI
    任务: fix-phase3-validation-error
    修改内容: 添加 phase3_candidates_per_batch 配置，控制每批处理的候选数量
    """

    annotation: bool = False
    annotation_fallback: bool = True
    incremental_disambig: bool = True
    mention_extraction: bool = False
    full_disambig: bool = True
    level3_rerank: bool = False
    diagnosis: bool = True
    phase3_candidates_per_batch: int = 5

    def validate(self) -> None:
        """验证配置"""
        pass


@dataclass
class StreamingSettings:
    """
    各任务streaming开关配置

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 支持流式响应模式配置
    """

    annotation: bool = False
    annotation_fallback: bool = True
    incremental_disambig: bool = True
    mention_extraction: bool = False
    full_disambig: bool = True
    level3_rerank: bool = False
    diagnosis: bool = True
    cloud_only: bool = True  # 是否仅在云端模型启用流式模式

    def validate(self) -> None:
        """验证配置"""
        pass


@dataclass
class StructuredOutputSettings:
    """
    结构化输出模式配置。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    说明: 集中配置各任务默认使用 json_schema / json_object / instructor_json，
          避免业务模块散落 provider 兼容判断。
    """

    annotation: str = "json_schema"
    annotation_fallback: str = "json_object"
    incremental_disambig: str = "json_schema"
    mention_extraction: str = "json_object"
    full_disambig: str = "json_schema"
    level3_rerank: str = "json_schema"
    diagnosis: str = "json_schema"


_STRUCTURED_OUTPUT_ALLOWED_MODES = {"json_schema", "json_object", "instructor_json"}


def _parse_structured_output_mode(data: dict[str, Any], key: str, default: str) -> str:
    """
    解析单个结构化输出模式。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: 对配置里的 mode 做白名单校验，避免拼写错误静默退回导致 provider 行为不可解释。
    """
    mode = data.get(key, default)
    if mode not in _STRUCTURED_OUTPUT_ALLOWED_MODES:
        allowed = ", ".join(sorted(_STRUCTURED_OUTPUT_ALLOWED_MODES))
        raise ValueError(f"structured_output.{key} 必须是以下值之一: {allowed}")
    return mode


def _parse_structured_output_settings(data: dict[str, Any] | None) -> StructuredOutputSettings:
    """
    解析结构化输出模式配置。

    创建时间: 2026-04-24
    任务: structured-output-adapter-instructor-unification
    新建原因: 将结构化输出 mode 从业务代码中抽到项目级配置，便于按 provider 能力调整。
    """
    json_data = data or {}
    defaults = StructuredOutputSettings()
    return StructuredOutputSettings(
        annotation=_parse_structured_output_mode(json_data, "annotation", defaults.annotation),
        annotation_fallback=_parse_structured_output_mode(
            json_data,
            "annotation_fallback",
            defaults.annotation_fallback,
        ),
        incremental_disambig=_parse_structured_output_mode(
            json_data,
            "incremental_disambig",
            defaults.incremental_disambig,
        ),
        mention_extraction=_parse_structured_output_mode(
            json_data,
            "mention_extraction",
            defaults.mention_extraction,
        ),
        full_disambig=_parse_structured_output_mode(json_data, "full_disambig", defaults.full_disambig),
        level3_rerank=_parse_structured_output_mode(json_data, "level3_rerank", defaults.level3_rerank),
        diagnosis=_parse_structured_output_mode(json_data, "diagnosis", defaults.diagnosis),
    )


def _get_env_var(prefix: str, suffix: str, default: str | None = None) -> str | None:
    """获取环境变量值"""
    return os.getenv(f"{prefix}_{suffix}", default)


def _parse_task_model_settings(data: dict[str, Any] | None, env_prefix: str = "") -> TaskModelSettings:
    """
    解析任务模型配置

    修改时间: 2026-03-21
    修改者: TraeAI
    任务: migrate-litellm-to-openai-sdk
    修改内容: 移除 backend_name 字段

    修改时间: 2026-04-20
    修改者: Codex
    任务: 清理无效模型配置项
    修改内容: 不再解析 provider 和模型级 max_retries，避免配置看似可调但运行时无效
    """
    env_base_url = _get_env_var(env_prefix, "BASE_URL")
    env_model = _get_env_var(env_prefix, "MODEL")
    env_api_key = _get_env_var(env_prefix, "API_KEY")
    env_timeout = _get_env_var(env_prefix, "TIMEOUT_S")

    json_data = data or {}

    timeout_val = None
    if env_timeout:
        try:
            timeout_val = float(env_timeout)
        except ValueError:
            pass
    elif json_data.get("timeout_s") is not None:
        timeout_val = json_data.get("timeout_s")

    return TaskModelSettings(
        base_url=env_base_url or json_data.get("base_url"),
        model=env_model or json_data.get("model"),
        api_key=env_api_key or json_data.get("api_key"),
        timeout_s=timeout_val,
        temperature=json_data.get("temperature", 0.7),
        top_p=json_data.get("top_p", 0.8),
        top_k=json_data.get("top_k", 20),
        presence_penalty=json_data.get("presence_penalty", 1.5),
    )


def _parse_embedding_model_settings(data: dict[str, Any] | None, env_prefix: str = "") -> EmbeddingModelSettings:
    """
    解析嵌入模型配置

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 支持从环境变量覆盖配置，优先级：环境变量 > JSON配置

    修改时间: 2026-04-20
    修改者: Codex
    任务: 清理无效模型配置项
    修改内容: 删除模型级 max_retries 解析，保留真正被运行时消费的 embedding_dim

    修改时间: 2026-04-20
    修改者: Codex (GPT-5)
    任务: fix-embedding-dimension-config-contract
    修改内容: 恢复 embedding_dim 的显式配置契约。系统只信任 settings/env 中声明的维度，
              首次建表使用配置值，后续由“代码配置/模型返回/数据库表结构”三方一致性校验决定是否继续执行。

    修改时间: 2026-04-20
    修改者: Codex (GPT-5)
    任务: batch-embedding-requests
    修改内容: 增加 batch_size 配置，控制语义分块批量请求 embedding API 时每批发送的文本数。
    """
    env_base_url = _get_env_var(env_prefix, "BASE_URL")
    env_model = _get_env_var(env_prefix, "MODEL")
    env_api_key = _get_env_var(env_prefix, "API_KEY")
    env_timeout = _get_env_var(env_prefix, "TIMEOUT_S")
    env_embedding_dim = _get_env_var(env_prefix, "EMBEDDING_DIM")
    env_batch_size = _get_env_var(env_prefix, "BATCH_SIZE")

    json_data = data or {}

    timeout_val = None
    if env_timeout:
        try:
            timeout_val = float(env_timeout)
        except ValueError:
            pass
    elif json_data.get("timeout_s") is not None:
        timeout_val = json_data.get("timeout_s")

    embedding_dim_val = 1536
    if env_embedding_dim:
        try:
            embedding_dim_val = int(env_embedding_dim)
        except ValueError:
            embedding_dim_val = json_data.get("embedding_dim", 1536)
    else:
        embedding_dim_val = json_data.get("embedding_dim", 1536)

    batch_size_val = 8
    if env_batch_size:
        try:
            batch_size_val = int(env_batch_size)
        except ValueError:
            batch_size_val = json_data.get("batch_size", 8)
    else:
        batch_size_val = json_data.get("batch_size", 8)

    return EmbeddingModelSettings(
        base_url=env_base_url or json_data.get("base_url"),
        model=env_model or json_data.get("model"),
        api_key=env_api_key or json_data.get("api_key"),
        timeout_s=timeout_val,
        embedding_dim=embedding_dim_val,
        batch_size=batch_size_val,
    )


def _parse_models_settings(data: dict[str, Any] | None) -> ModelsSettings:
    """
    解析任务级模型配置集合

    修改时间: 2026-03-16
    修改者: TraeAI
    修改内容: 传递环境变量前缀给各模型配置解析器

    修改时间: 2026-04-20
    修改者: Codex
    任务: refactor-role-based-model-client-names
    修改内容: 将 cloud_annotation 配置解析重命名为 annotation_fallback
    """
    if not data:
        data = {}
    return ModelsSettings(
        annotation=_parse_task_model_settings(data.get("annotation"), "ANNOTATION"),
        annotation_fallback=_parse_task_model_settings(
            data.get("annotation_fallback"),
            "ANNOTATION_FALLBACK",
        ),
        incremental_disambig=_parse_task_model_settings(data.get("incremental_disambig"), "INCREMENTAL_DISAMBIG"),
        mention_extraction=_parse_task_model_settings(data.get("mention_extraction"), "MENTION_EXTRACTION"),
        semantic_chunking=_parse_embedding_model_settings(data.get("semantic_chunking"), "SEMANTIC_CHUNKING"),
        full_disambig=_parse_task_model_settings(data.get("full_disambig"), "FULL_DISAMBIG"),
        level3_rerank=_parse_task_model_settings(data.get("level3_rerank"), "LEVEL3_RERANK"),
        diagnosis=_parse_task_model_settings(data.get("diagnosis"), "DIAGNOSIS"),
    )


def _parse_thinking_settings(data: dict[str, Any] | None) -> ThinkingSettings:
    """
    解析thinking配置

    创建时间: 2026-03-12
    创建者: TraeAI
    任务: 将thinking配置从各模型配置中独立出来

    修改时间: 2026-03-16
    修改者: TraeAI
    任务: 修复thinking参数传递方式
    修改内容: 配置加载失败时抛出错误，而非使用默认值
    """
    if not data:
        raise ValueError("thinking 配置不能为空，请检查 config/settings.json 中的 thinking 配置项")
    return ThinkingSettings(
        annotation=data.get("annotation", False),
        annotation_fallback=data.get("annotation_fallback", True),
        incremental_disambig=data.get("incremental_disambig", True),
        mention_extraction=data.get("mention_extraction", False),
        full_disambig=data.get("full_disambig", True),
        level3_rerank=data.get("level3_rerank", False),
        diagnosis=data.get("diagnosis", True),
    )


def _parse_streaming_settings(data: dict[str, Any] | None) -> StreamingSettings:
    """
    解析streaming配置

    创建时间: 2026-03-16
    创建者: TraeAI
    任务: 支持流式响应模式配置
    """
    if not data:
        return StreamingSettings()
    return StreamingSettings(
        annotation=data.get("annotation", False),
        annotation_fallback=data.get("annotation_fallback", True),
        incremental_disambig=data.get("incremental_disambig", True),
        mention_extraction=data.get("mention_extraction", False),
        full_disambig=data.get("full_disambig", True),
        level3_rerank=data.get("level3_rerank", False),
        diagnosis=data.get("diagnosis", True),
        cloud_only=data.get("cloud_only", True),
    )
