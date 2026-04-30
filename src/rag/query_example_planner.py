"""
Level3 规则 query example planner

创建时间: 2026-04-30
任务: level3-query-exampler-mainline
说明: 复用现有描述性人物正则能力，为 identity 高阶链提供轻量 query example，
      让规则路径先于 LLM 路径执行，只有规则无果时才允许继续升级。
"""

from __future__ import annotations

from src.rag.mention_extraction import extract_person_mentions
from src.rag.mention_extraction_service import normalize_person_mentions
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.query_example_types import Level3ExpansionQuery, QueryExamplePlannerRequest, QueryExamplePlannerResult


def collect_descriptive_anchor_texts(
    text: str,
    *,
    names_in_chunk: tuple[str, ...] = (),
    run_id: str | None = None,
    current_chunk: int | None = None,
) -> tuple[str, ...]:
    """
    创建时间: 2026-04-30
    修改时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 二级门槛只关心“正文里是否存在未解析的描述性人物锚点”；
          这里保留规则命中的 raw anchor 文本，供 direct gate 与 LLM fallback 共用。
    修改原因: direct gate 与规则 planner 必须共享同一套 unresolved-anchor 过滤口径，
              不能在 raw regex 命中层就把已解析 target 名重新当成描述性锚点拉回高阶链。
    """

    normalized_mentions = normalize_person_mentions(
        extract_person_mentions(text),
        request=MentionExtractionRequest(
            text=text,
            names_in_chunk=names_in_chunk,
            context_text=text,
            run_id=run_id,
            current_chunk=current_chunk,
        ),
        fallback_source="rule",
    )
    anchors: list[str] = []
    for mention in normalized_mentions:
        raw_text = mention.raw_text.strip()
        if raw_text and raw_text not in anchors:
            anchors.append(raw_text)
    return tuple(anchors)


def build_rule_query_examples(request: QueryExamplePlannerRequest) -> QueryExamplePlannerResult:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 规则 planner 只产出 1-2 条高置信 query example；
          优先压缩特征词组合，其次保留单条 raw anchor，不再为同一锚点扩成 3-4 种变体。
    """

    max_queries = min(max(request.max_queries, 0), 2)
    if max_queries <= 0:
        return QueryExamplePlannerResult(should_expand=False, reason="no_query_budget")

    normalized_mentions = normalize_person_mentions(
        extract_person_mentions(request.text),
        request=MentionExtractionRequest(
            text=request.text,
            names_in_chunk=tuple(dict.fromkeys(request.requested_names + request.seed_entities)),
            context_text=request.text,
            run_id=request.run_id,
            current_chunk=request.current_chunk,
        ),
        fallback_source="rule",
    )
    all_queries = build_query_examples_from_mentions(normalized_mentions, query_source="rule")
    kept_queries = all_queries[:max_queries]
    dropped_queries = _build_dropped_queries(all_queries[max_queries:])
    if not kept_queries:
        return QueryExamplePlannerResult(
            should_expand=False,
            reason="rule_anchor_detected_but_no_query_example",
            dropped_queries=dropped_queries,
        )
    return QueryExamplePlannerResult(
        should_expand=True,
        reason="rule_query_example_available",
        queries=kept_queries,
        dropped_queries=dropped_queries,
    )


def build_query_examples_from_mentions(
    mentions: list[PersonMention],
    *,
    query_source: str | None,
) -> list[Level3ExpansionQuery]:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 把已归一化的描述性人物锚点转成少量 query example；
          规则与 LLM 都复用同一组 query 去重与优先级逻辑。
    """

    queries: list[Level3ExpansionQuery] = []
    seen_query_texts: set[str] = set()
    for mention in mentions:
        role_words = _as_string_list(mention.cues.get("role_word"))
        appearance = _as_string_list(mention.cues.get("appearance"))
        locations = _as_string_list(mention.cues.get("location"))
        actions = _as_string_list(mention.cues.get("action"))
        matched_features = tuple(dict.fromkeys(appearance + locations + role_words + actions))

        variants: list[tuple[str, str]] = []
        compressed_query = _build_compressed_query(mention, matched_features)
        if compressed_query:
            variants.append(("mention_compressed", compressed_query))

        raw_anchor = mention.raw_text.strip()
        if raw_anchor:
            variants.append(("mention_raw", raw_anchor))

        for query_variant, query_text in variants:
            normalized_query = " ".join(query_text.split())
            if not normalized_query or normalized_query in seen_query_texts:
                continue
            seen_query_texts.add(normalized_query)
            queries.append(
                Level3ExpansionQuery(
                    query_text=normalized_query,
                    anchor_text=raw_anchor,
                    anchor_type=mention.mention_type,
                    query_variant=query_variant,
                    query_source=query_source or mention.source or "rule",
                    matched_features=matched_features,
                    confidence=mention.confidence,
                )
            )
    return queries


def _build_compressed_query(mention: PersonMention, matched_features: tuple[str, ...]) -> str | None:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: query exampler 优先返回短 query；
          若已有 LLM 归一化特征则直接复用，否则退化为规则抽出的可区分特征词组合。
    """

    if mention.normalized_query_terms:
        return " ".join(term for term in mention.normalized_query_terms if term)
    if not matched_features:
        return None
    compressed = " ".join(matched_features)
    raw_anchor = " ".join(mention.raw_text.split())
    if not compressed or compressed == raw_anchor:
        return None
    return compressed


def _build_dropped_queries(queries: list[Level3ExpansionQuery]) -> list[dict[str, str]]:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: planner budget 被裁掉的 query 也要进入 generation_meta，
          便于后续复盘“为什么没有继续放大 query 池”。
    """

    return [
        {
            "query_text": query.query_text,
            "mention_text": query.anchor_text,
            "query_variant": query.query_variant,
            "reason": "max_queries_budget",
        }
        for query in queries
    ]


def _as_string_list(value: object) -> list[str]:
    """
    创建时间: 2026-04-30
    任务: level3-query-exampler-mainline
    说明: 统一读取 cues 里的字符串/数组字段，避免规则 planner 依赖隐式类型分支。
    """

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
