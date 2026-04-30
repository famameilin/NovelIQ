"""
Level3 LLM query example planner

创建时间: 2026-04-30
任务: level3-query-exampler-mainline
说明: 只有在 identity 文本已检测到描述性人物锚点、但规则 planner 产空时，
      才允许调用本模块补 1-2 条高置信 query example。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.rag.model_call_audit import audited_structured_model_call
from src.rag.query_example_planner import _build_dropped_queries
from src.rag.query_example_types import (
    Level3ExpansionQuery,
    QueryExamplePlannerRequest,
    QueryExamplePlannerResult,
)


class LLMQueryExampleItem(BaseModel):
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: LLM planner 单条 query example 输出；只保留检索真正需要的短 query、
          对应锚点和简短理由，不再要求结构化人物 cues。
    """

    model_config = ConfigDict(extra="forbid")

    query_text: str
    anchor_text: str
    reason: str = ""
    confidence: float | None = None


class LLMQueryExampleResponse(BaseModel):
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: LLM planner 顶层响应；允许显式返回 should_expand=false，
          用于表达“当前 direct query 已经够用，不需要额外扩展”。
    """

    model_config = ConfigDict(extra="forbid")

    should_expand: bool = False
    reason: str = ""
    queries: list[LLMQueryExampleItem] = Field(default_factory=list)


class LLMLevel3QueryExamplePlanner:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 复用现有 OpenAI-compatible BaseModelClient 能力执行结构化 query planner，
          配置仍沿用 mention_extraction transport alias，不额外分叉模型接线。
    """

    def __init__(self, model_client: Any, *, enable_thinking: bool = False) -> None:
        self._model_client = model_client
        self._enable_thinking = enable_thinking

    async def plan_queries(self, request: QueryExamplePlannerRequest) -> QueryExamplePlannerResult:
        """
        创建时间: 2026-04-30
        任务: level3-query-exampler-mainline
        说明: 只返回 query example planner 结果；是否真正采用这些 query，
              由上游 `build_level3_query_plan()` 结合 direct base query 统一决策。
        """

        messages = _build_messages(request)
        timeout = getattr(self._model_client, "_config", None) and getattr(
            self._model_client._config, "timeout_s", None
        )
        return await audited_structured_model_call(
            self._model_client,
            messages=messages,
            response_model=LLMQueryExampleResponse,
            normalize_response=lambda response: normalize_query_example_response(response, request=request),
            interaction_type="level3_query_planner",
            phase="level3_query_planner",
            call_type="level3_query_planner",
            enable_thinking=self._enable_thinking,
            timeout=timeout,
            run_id=request.run_id,
            chunk_id=request.current_chunk,
        )


def normalize_query_example_response(
    response_data: LLMQueryExampleResponse,
    *,
    request: QueryExamplePlannerRequest,
) -> QueryExamplePlannerResult:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 把结构化 LLM 响应归一化为内部 planner 结果，并在这里统一裁掉超预算 query。
    """

    max_queries = min(max(request.max_queries, 0), 2)
    all_queries: list[Level3ExpansionQuery] = []
    seen_query_texts: set[str] = set()
    for item in response_data.queries:
        query_text = " ".join(item.query_text.split())
        anchor_text = " ".join(item.anchor_text.split())
        if not query_text or query_text in seen_query_texts:
            continue
        seen_query_texts.add(query_text)
        all_queries.append(
            Level3ExpansionQuery(
                query_text=query_text,
                anchor_text=anchor_text or query_text,
                anchor_type="descriptive_person",
                query_variant="mention_compressed",
                query_source="llm",
                matched_features=tuple(part for part in query_text.split(" ") if part),
                confidence=item.confidence,
            )
        )

    kept_queries = all_queries[:max_queries]
    dropped_queries = _build_dropped_queries(all_queries[max_queries:])
    should_expand = bool(response_data.should_expand and kept_queries)
    return QueryExamplePlannerResult(
        should_expand=should_expand,
        reason=(response_data.reason or "").strip() or "llm_query_example_decision",
        queries=kept_queries if should_expand else [],
        dropped_queries=dropped_queries,
    )


def _build_messages(request: QueryExamplePlannerRequest) -> list[dict[str, str]]:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: prompt 明确要求模型只做“是否需要补 query example”的轻量判断，
          不再执行结构化人物信息抽取，也不允许输出超过 2 条 query。
    """

    requested_names = _join_limited_texts(request.requested_names)
    seed_entities = _join_limited_texts(request.seed_entities)
    anchor_candidates = _join_limited_texts(request.anchor_candidates)
    json_example = (
        '{"should_expand":true,"reason":"文本里有未解析的描述性人物锚点，direct query 不够区分。",'
        '"queries":[{"query_text":"灰布衫 瘦高 男人 门口","anchor_text":"门口那个穿灰布衫的瘦高男人",'
        '"reason":"外貌和位置特征足够稳定","confidence":0.86}]}'
    )
    user_content = (
        "你是小说 Level3 query example planner，只输出合法 JSON。\n"
        "任务：判断当前 identity 检索是否需要补充 1-2 条 query example。\n"
        "如果 direct query 已足够，请返回 should_expand=false 且 queries=[]。\n"
        "不要做身份猜测，不要复述已确认实名本身，不要输出超过 2 条 query。\n"
        "query_text 应尽量短，只保留最能区分人物的锚点短语或特征词组合。\n"
        f"JSON 输出格式样例：{json_example}\n"
        f"当前 consumer target：{requested_names}\n"
        f"可用检索锚点：{seed_entities}\n"
        f"已检测到的描述性人物锚点：{anchor_candidates}\n"
        f"待处理文本：{request.text}"
    )
    return [
        {"role": "system", "content": "你是小说检索 query planner，只输出结构化 JSON。"},
        {"role": "user", "content": user_content},
    ]


def _join_limited_texts(values: tuple[str, ...], *, limit: int = 8) -> str:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 控制 prompt 里名字/锚点列表长度，避免 planner prompt 因上下文枚举过多而再次膨胀。
    """

    normalized: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in normalized:
            normalized.append(text[:24])
        if len(normalized) >= limit:
            break
    return "、".join(normalized) if normalized else "无"
