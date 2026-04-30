"""
Level3 query example planner 共享类型

创建时间: 2026-04-30
任务: level3-query-exampler-mainline
说明: 将 Level3 identity 高阶链收口为 query example planner 主线，
      显式区分 planner 请求、planner 结果与最终 expansion query 合同。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

QueryPlannerKind = Literal["disabled", "direct_gate", "rule_example", "llm_query_example"]


@dataclass(frozen=True, slots=True)
class Level3ExpansionQuery:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 单条 Level3 expansion query 合同；metadata 仍复用旧 mention 字段名，
          但领域语义已经收口为 query example，而不是结构化人物抽取结果本身。
    """

    query_text: str
    anchor_text: str
    anchor_type: str
    query_variant: str = "mention_raw"
    query_source: str = "rule"
    matched_features: tuple[str, ...] = ()
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class QueryExamplePlannerRequest:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: query planner 的最小请求上下文；只暴露 direct query、可信名字锚点、
          已检测到的描述性人物锚点以及本次预算，不把 workflow 弱语义参数泄漏进 planner。
    """

    text: str
    requested_names: tuple[str, ...] = ()
    seed_entities: tuple[str, ...] = ()
    anchor_candidates: tuple[str, ...] = ()
    run_id: str | None = None
    current_chunk: int | None = None
    max_queries: int = 2


@dataclass(frozen=True, slots=True)
class QueryExamplePlannerResult:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: planner 标准输出；无论来源是规则还是 LLM，都统一表达是否需要扩展、
          为什么扩展以及哪些 query 因预算被裁掉。
    """

    should_expand: bool
    reason: str
    queries: list[Level3ExpansionQuery] = field(default_factory=list)
    dropped_queries: list[dict[str, str]] = field(default_factory=list)


class Level3QueryExamplePlanner(Protocol):
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: LLM query planner 的最小协议；外层只依赖 `plan_queries()`，
          不依赖具体 provider 或 transport 实现。
    """

    async def plan_queries(self, request: QueryExamplePlannerRequest) -> QueryExamplePlannerResult:
        """根据请求上下文返回 query example planner 结果。"""
