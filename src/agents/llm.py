"""
LangChain 模型桥接

将项目 TaskModelConfig（base_url/model/api_key/thinking）桥接到 langchain-openai ChatOpenAI
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessageChunk, BaseMessageChunk
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.config import TaskModelConfig, TaskType, load_task_config

_reasoning_content_patch_installed = False


def _install_reasoning_content_patch() -> None:
    """
    2026-08-10 用于修复 langchain-openai 流式解析丢弃 reasoning_content 的问题

    langchain-openai 1.4.1/1.4.3 的 _convert_delta_to_message_chunk 只提取
    content / function_call / tool_calls，Qwen 系网关返回的 delta.reasoning_content
    被静默丢弃（官方 docstring 明确不转发），导致审计与流式聚合探测不到思考内容。
    这里包装该函数，把 reasoning_content 增量合并进 additional_kwargs。
    """
    global _reasoning_content_patch_installed
    if _reasoning_content_patch_installed:
        return

    import langchain_openai.chat_models.base as base

    original = base._convert_delta_to_message_chunk

    def _patched_convert(
        delta: Mapping[str, Any],
        default_class: type[BaseMessageChunk],
    ) -> BaseMessageChunk:
        message = original(delta, default_class)
        reasoning = delta.get("reasoning_content")
        if reasoning and isinstance(message, AIMessageChunk):
            previous = message.additional_kwargs.get("reasoning_content", "")
            message.additional_kwargs["reasoning_content"] = previous + str(reasoning)
        return message

    base._convert_delta_to_message_chunk = _patched_convert  # type: ignore[assignment]
    _reasoning_content_patch_installed = True


def build_chat_model(
    task_type: TaskType = "annotation",
    config: TaskModelConfig | None = None,
) -> ChatOpenAI:
    """
    根据任务类型构建 ChatOpenAI 实例

    - 复用项目统一的模型配置（base_url / model / api_key / temperature）
    - thinking 启用时透传 `extra_body={"think": True}`（Qwen 系 OpenAI 兼容服务）
    - 构建时安装 reasoning_content 流式补丁（幂等）
    """
    _install_reasoning_content_patch()
    cfg = config or load_task_config(task_type)
    cfg.validate()

    extra_body: dict[str, object] | None = None
    if cfg.thinking_enabled:
        extra_body = {"think": True}
    # 2026-10-03 流式必须显式开 include_usage：否则网关不下发 usage 块，token 记账
    # 退化成本地估算（思考 token 完全漏记——此前 completion 只记到可见文本 41K，
    # 真实思考输出数百万 token 全部隐身）。聚合器（stream_aggregator）会把末 chunk
    # 的 usage_metadata 装回响应，extract_agent_token_usage 据此拿到如实上报。
    extra_body = {**(extra_body or {}), "stream_options": {"include_usage": True}}

    # 2026-10-02 删除"流式输出"设置与非流式兜底路径：LLM 调用固定开启流式，
    # 断流重试与计时统一由 stream.py 按 total_attempts 处理
    return ChatOpenAI(
        model=cfg.model or "",
        base_url=cfg.base_url,
        api_key=SecretStr(cfg.api_key) if cfg.api_key else None,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        # 2026-09-11 显式补全上限 128K：思考模式 provider 默认值随模式漂移，
        # 截断实测 7.7K~61K 字符散布，思考撑满预算时载荷尾部被腰斩。
        # langchain-openai 新版参数名为 max_completion_tokens（OpenAI 新参数，旧 max_tokens 已弃用）
        max_completion_tokens=cfg.max_tokens,
        timeout=cfg.timeout_s if cfg.timeout_s is not None else 120,
        streaming=True,
        # 2026-10-03 流块间隙看门狗放宽到 600s：run 4a6c268c 诊断阶段长报告生成中途
        # 停流 120s 被默认看门狗掐死（已收 1400 chunk）。Ark 网关限流队列/思考停顿
        # 超 2 分钟是常态；真死连接仍由 httpx 读超时兜底，10 分钟间隙容忍不引入悬挂。
        stream_chunk_timeout=600,
        # 2026-08-12 断流重试由 stream.py 按 total_attempts 统一负责；
        # SDK 层再叠加 max_retries 会让最坏请求次数成倍膨胀（流式中断时叠加后最多 8 次）。
        # 关闭 SDK 层重试，重试次数只由 total_attempts 一处配置决定。
        max_retries=0,
        extra_body=extra_body,
    )
