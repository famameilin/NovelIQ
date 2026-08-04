"""
LangChain 模型桥接

将项目 TaskModelConfig（base_url/model/api_key/thinking）桥接到 langchain-openai ChatOpenAI
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.config import TaskModelConfig, TaskType, load_task_config


def build_chat_model(
    task_type: TaskType = "annotation",
    config: TaskModelConfig | None = None,
) -> ChatOpenAI:
    """
    根据任务类型构建 ChatOpenAI 实例

    - 复用项目统一的模型配置（base_url / model / api_key / temperature）
    - thinking 启用时透传 `extra_body={"think": True}`（Qwen 系 OpenAI 兼容服务）
    """
    cfg = config or load_task_config(task_type)
    cfg.validate()

    extra_body: dict[str, object] | None = None
    if cfg.thinking_enabled:
        extra_body = {"think": True}

    base_url = (cfg.base_url or "").lower()
    is_local_endpoint = any(host in base_url for host in ("localhost", "127.0.0.1", "host.docker.internal"))
    streaming = cfg.stream_enabled and (not cfg.stream_cloud_only or not is_local_endpoint)

    return ChatOpenAI(
        model=cfg.model or "",
        base_url=cfg.base_url,
        api_key=SecretStr(cfg.api_key) if cfg.api_key else None,
        temperature=cfg.temperature,
        top_p=cfg.top_p,
        timeout=cfg.timeout_s if cfg.timeout_s is not None else 120,
        streaming=streaming,
        max_retries=1,
        extra_body=extra_body,
    )
