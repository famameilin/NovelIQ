"""
LLM mention extraction 边界。

创建时间: 2026-04-24
任务: llm-mention-rerank-chain
说明: 封装模型调用与结构化响应转换；本模块只抽人物 mention，不做身份裁决。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention


class LLMPersonMentionItem(BaseModel):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM 单条 mention 输出 schema，字段保持与 PersonMention 兼容。
    """

    raw_text: str
    mention_type: str = "descriptive_person"
    sentence_text: str = ""
    cues: dict[str, str | list[str]] = Field(default_factory=dict)
    confidence: float | None = None
    span_start: int | None = None
    span_end: int | None = None
    normalized_query_terms: list[str] = Field(default_factory=list)


class LLMPersonMentionResponse(BaseModel):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM mention extraction 的顶层结构化响应。
    """

    mentions: list[LLMPersonMentionItem] = Field(default_factory=list)


class LLMPersonMentionExtractor:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 复用现有 OpenAI-compatible BaseModelClient 能力执行结构化 mention extraction。
    """

    def __init__(self, model_client: Any, *, enable_thinking: bool = False) -> None:
        self._model_client = model_client
        self._enable_thinking = enable_thinking

    async def extract_mentions(self, request: MentionExtractionRequest) -> list[PersonMention]:
        """
        创建时间: 2026-04-24
        任务: llm-mention-rerank-chain
        说明: 调用 LLM 产出结构化 mention；调用失败由 service 统一记录并回退规则版。
        """
        messages = _build_messages(request)
        # 显式传递 timeout 避免无限阻塞；模型配置自带 timeout_s，优先使用。
        timeout = getattr(self._model_client, "_config", None) and getattr(
            self._model_client._config, "timeout_s", None
        )
        response = await self._model_client._call_api(
            messages,
            enable_thinking=self._enable_thinking,
            response_model=LLMPersonMentionResponse,
            timeout=timeout,
        )
        parsed = (
            response
            if isinstance(response, LLMPersonMentionResponse)
            else self._model_client._parse_structured_response(response, LLMPersonMentionResponse)
        )
        return [_to_person_mention(item) for item in parsed.mentions]


def _build_messages(request: MentionExtractionRequest) -> list[dict[str, str]]:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 构造最小任务提示，明确 LLM 只负责抽取描述性人物指代，不允许输出身份判断。
    """
    names_text = "、".join(request.names_in_chunk) if request.names_in_chunk else "无"
    context_text = request.context_text or ""
    user_content = (
        "请从文本中抽取人物/角色型描述性 mention，输出 JSON。\n"
        "约束：不抽纯场景，不做身份猜测，不输出宽泛无区分度 mention，不把已出现的实名当 mention。\n"
        "每条 mention 必须来自原文，并尽量给出外貌、动作、位置、角色词等 cues。\n"
        f"当前显式名字列表：{names_text}\n"
        f"相邻/共享上下文：{context_text}\n"
        f"待抽取文本：{request.text}"
    )
    return [
        {"role": "system", "content": "你是小说人物 mention extraction 模块，只输出结构化 JSON。"},
        {"role": "user", "content": user_content},
    ]


def _to_person_mention(item: LLMPersonMentionItem) -> PersonMention:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 将 Pydantic schema 转为 RAG 内部 DTO，source 固定标记为 llm。
    """
    return PersonMention(
        raw_text=item.raw_text,
        mention_type=item.mention_type,
        sentence_text=item.sentence_text,
        cues=item.cues,
        confidence=item.confidence,
        span_start=item.span_start,
        span_end=item.span_end,
        normalized_query_terms=tuple(item.normalized_query_terms),
        source="llm",
    )
