from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TaskModelConfig:
    """
    任务级模型配置
    """

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_s: float | None = None
    temperature: float = 0.7
    top_p: float = 0.8
    thinking_enabled: bool = False
    thinking_budget_tokens: int | None = None
    max_tokens: int | None = None
    # 2026-10-02 删除 stream_enabled 字段：流式输出固定开启（src/agents/llm.py），不再随任务配置
    provider_id: str = "default"
    max_in_flight: int = 8

    def validate(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.base_url is None:
            raise ValueError("base_url 不能为空")
        if self.model is None:
            raise ValueError("model 不能为空")


TaskType = Literal[
    "annotation",
    "diagnosis",
]
