"""
LLM mention extraction 边界

封装模型调用与结构化响应转换；本模块只抽人物 mention，不做身份裁决
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.config import settings
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.model_call_audit import audited_structured_model_call


class LLMPersonMentionItem(BaseModel):
    """
    LLM 单条 mention 输出 schema，字段保持与 PersonMention 兼容
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
    LLM mention extraction 的顶层结构化响应
    """

    mentions: list[LLMPersonMentionItem] = Field(default_factory=list)


class LLMPersonMentionCloudItem(BaseModel):
    """
    云端 strict schema 不稳定支持动态 dict[str, ...] 字段；
          这里将 cues 显式展开为固定字段，返回后再归一化回内部 PersonMention.cues
    """

    model_config = ConfigDict(extra="forbid")

    raw_text: str
    mention_type: str = "descriptive_person"
    sentence_text: str = ""
    role_word: str = ""
    appearance: list[str] = Field(default_factory=list)
    action: list[str] = Field(default_factory=list)
    location: list[str] = Field(default_factory=list)
    confidence: float | None = None
    span_start: int | None = None
    span_end: int | None = None
    normalized_query_terms: list[str] = Field(default_factory=list)


class LLMPersonMentionCloudResponse(BaseModel):
    """
    云端兼容的 mention extraction 顶层结构，避免动态键对象被 strict provider 拒绝
    """

    model_config = ConfigDict(extra="forbid")

    mentions: list[LLMPersonMentionCloudItem] = Field(default_factory=list)


class LLMPersonMentionExtractor:
    """
    复用现有 OpenAI-compatible BaseModelClient 能力执行结构化 mention extraction
    """

    def __init__(self, model_client: Any, *, enable_thinking: bool = False) -> None:
        self._model_client = model_client
        self._enable_thinking = enable_thinking

    async def extract_mentions(self, request: MentionExtractionRequest) -> list[PersonMention]:
        """
        调用 LLM 产出结构化 mention；调用失败由 service 统一记录并回退规则版

        移除本模块里的 json_object 特判，结构化输出 mode 统一交给适配层选择
        """
        messages = _build_messages(request)
        response_model = _select_response_model(self._model_client)
        # 显式传递 timeout 避免无限阻塞；模型配置自带 timeout_s，优先使用
        timeout = getattr(self._model_client, "_config", None) and getattr(
            self._model_client._config, "timeout_s", None
        )
        return await audited_structured_model_call(
            self._model_client,
            messages=messages,
            response_model=response_model,
            normalize_response=normalize_mention_response,
            interaction_type="mention_extraction",
            phase="mention_extraction",
            call_type="mention_extraction",
            enable_thinking=self._enable_thinking,
            timeout=timeout,
            run_id=request.run_id,
            chunk_id=request.current_chunk,
        )


def _select_response_model(model_client: Any) -> type[LLMPersonMentionResponse] | type[LLMPersonMentionCloudResponse]:
    """
    复用仓库里“云端 provider 走 cloud-safe schema，本地保留原生 schema”的既有模式
    """
    is_cloud_api = getattr(model_client, "is_cloud_api", None)
    if callable(is_cloud_api) and is_cloud_api():
        return LLMPersonMentionCloudResponse
    return LLMPersonMentionResponse


def normalize_mention_response(
    response_data: LLMPersonMentionResponse | LLMPersonMentionCloudResponse,
) -> list[PersonMention]:
    """
    将本地/云端两套结构化 schema 统一归一化为内部 PersonMention，避免影响下游 query builder
    """
    if isinstance(response_data, LLMPersonMentionResponse):
        return [_to_person_mention(item) for item in response_data.mentions]
    return [_to_person_mention_from_cloud(item) for item in response_data.mentions]


def _build_messages(request: MentionExtractionRequest) -> list[dict[str, str]]:
    """
    构造最小任务提示，明确 LLM 只负责抽取描述性人物指代，不允许输出身份判断

    增加明确 JSON 输出样例，满足 DeepSeek JSON Output 对 prompt 的要求
    """
    limited_names = _limit_seed_entities(request.names_in_chunk)
    names_text = "、".join(limited_names) if limited_names else "无"
    context_text = _build_prompt_context_text(request)
    mention_limit = min(max(settings.rag.level3_max_queries, 1), 6)
    json_example = (
        '{"mentions":[{"raw_text":"门口那个穿灰布衫的瘦高男人",'
        '"mention_type":"descriptive_person","sentence_text":"门口那个穿灰布衫的瘦高男人压低声音说话。",'
        '"role_word":"男人","appearance":["灰布衫","瘦高"],"action":["压低声音说话"],'
        '"location":["门口"],"confidence":0.9,"span_start":0,"span_end":14,'
        '"normalized_query_terms":["灰布衫","瘦高","男人","门口"]}]}'
    )
    user_content = (
        "请从文本中抽取人物/角色型描述性 mention，输出合法 JSON。\n"
        "约束：不抽纯场景，不做身份猜测，不输出宽泛无区分度 mention，不把已出现的实名当 mention。\n"
        f"每条 mention 必须来自原文，并尽量给出外貌、动作、位置、角色词等 cues，最多输出 {mention_limit} 条。\n"
        f"JSON 输出格式样例：{json_example}\n"
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
    将 Pydantic schema 转为 RAG 内部 DTO，source 固定标记为 llm
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


def _to_person_mention_from_cloud(item: LLMPersonMentionCloudItem) -> PersonMention:
    """
    将云端兼容 schema 转回内部 cues dict 合同；仅保留 query 层真正消费的固定 cue 键
    """
    return PersonMention(
        raw_text=item.raw_text,
        mention_type=item.mention_type,
        sentence_text=item.sentence_text,
        cues={
            "role_word": item.role_word,
            "appearance": list(item.appearance),
            "action": list(item.action),
            "location": list(item.location),
        },
        confidence=item.confidence,
        span_start=item.span_start,
        span_end=item.span_end,
        normalized_query_terms=tuple(item.normalized_query_terms),
        source="llm",
    )


def _limit_seed_entities(seed_entities: tuple[str, ...]) -> list[str]:
    """
    mention extraction prompt 只保留少量可信实体锚点，避免 alias/active entity 太多时把提示词挤爆
    """
    limited: list[str] = []
    for entity in seed_entities:
        text = str(entity).strip()
        if not text or text in limited:
            continue
        limited.append(text[:24])
        if len(limited) >= 8:
            break
    return limited


def _build_prompt_context_text(request: MentionExtractionRequest) -> str:
    """
    如果 context_text 与主文本相同，则不重复注入；避免 LLM prompt 因完全重复文本无意义膨胀
    """
    context_text = (request.context_text or "").strip()
    request_text = request.text.strip()
    if not context_text:
        return "无"
    if context_text == request_text:
        return "与待抽取文本相同，不重复注入"
    return context_text
