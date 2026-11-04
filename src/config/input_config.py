from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]
REASONING_EFFORTS: tuple[ReasoningEffort, ...] = ("low", "medium", "high", "xhigh", "max")
REASONING_EFFORT_LABELS: dict[str, str] = dict(zip(REASONING_EFFORTS, ("低", "中", "高", "极高", "最高"), strict=True))
DEFAULT_REASONING_EFFORT: ReasoningEffort = "high"


def validate_reasoning_effort(value: object) -> ReasoningEffort:
    """校验并返回五档思考等级"""
    if not isinstance(value, str) or value not in REASONING_EFFORTS:
        raise ValueError("reasoning_effort 必须为 low、medium、high、xhigh 或 max")
    return cast(ReasoningEffort, value)


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
    # 池内条目身份：容量与健康分按它记账，model 仍是发给端点的模型名
    entry_id: str | None = None
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT
    max_tokens: int | None = None
    # 上下文窗口容量：达到 90% 时压缩历史；None 表示不做容量压缩
    context_window_tokens: int | None = None
    provider_id: str = "default"
    max_in_flight: int = 8

    def validate(self) -> None:
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        validate_reasoning_effort(self.reasoning_effort)
        if self.base_url is None:
            raise ValueError("base_url 不能为空")
        if self.model is None:
            raise ValueError("model 不能为空")


TaskType = Literal[
    "annotation",
    "diagnosis",
]
