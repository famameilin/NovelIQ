"""
Level3 mention query 构造

将描述性人物 mention 转换为可复用的向量检索 query 变体
"""

from __future__ import annotations

from dataclasses import dataclass

from src.rag.mention_extraction_types import PersonMention


@dataclass(frozen=True, slots=True)
class MentionEvidenceQuery:
    """
    单条 mention 检索 query，携带可写入 EvidenceItem.metadata 的来源信息
    """

    query_text: str
    mention_text: str
    mention_type: str
    matched_features: tuple[str, ...]
    query_variant: str = "mention_raw"
    mention_source: str = "rule"
    mention_confidence: float | None = None


def _as_string_list(value: object) -> list[str]:
    """
    统一读取 PersonMention.cues 中的字符串列表字段，避免下游使用下标或隐式类型假设
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def build_mention_evidence_queries(mentions: list[PersonMention]) -> list[MentionEvidenceQuery]:
    """
    为每个 mention 构造“原文片段”和“线索词组合”两类 query，初版保持保守且可回归

    跳过缺少外貌/动作/位置线索的纯指代角色词，避免生成“少女/女子”等过宽 query

    支持 LLM normalized_query_terms 压缩 query，并给每条 query 标记 query_variant / mention_source
    """
    queries: list[MentionEvidenceQuery] = []
    seen_query_texts: set[str] = set()

    for mention in mentions:
        appearance = _as_string_list(mention.cues.get("appearance"))
        actions = _as_string_list(mention.cues.get("action"))
        locations = _as_string_list(mention.cues.get("location"))
        role_words = _as_string_list(mention.cues.get("role_word"))
        if mention.mention_type == "pronoun_role" and not (appearance or actions or locations):
            continue

        matched_features = tuple(dict.fromkeys(appearance + locations + role_words + actions))

        variants: list[tuple[str, str]] = [("mention_raw", mention.raw_text)]
        compressed_query = _build_compressed_query(mention, matched_features)
        if compressed_query:
            variants.append(("mention_compressed", compressed_query))
        compact_features = " ".join(matched_features)
        if compact_features and compact_features != mention.raw_text:
            variants.append(("mention_feature", compact_features))
        if actions:
            variants.append(("mention_feature", f"{mention.raw_text} {' '.join(actions)}"))

        for query_variant, query_text in variants:
            normalized = query_text.strip()
            if not normalized or normalized in seen_query_texts:
                continue
            seen_query_texts.add(normalized)
            queries.append(
                MentionEvidenceQuery(
                    query_text=normalized,
                    mention_text=mention.raw_text,
                    mention_type=mention.mention_type,
                    matched_features=matched_features,
                    query_variant=query_variant,
                    mention_source=mention.source,
                    mention_confidence=mention.confidence,
                )
            )

    return queries


def _build_compressed_query(mention: PersonMention, matched_features: tuple[str, ...]) -> str | None:
    """
    优先使用 LLM 提供的 normalized_query_terms；没有时只对超长 mention 用特征词压缩
    """
    if mention.normalized_query_terms:
        return " ".join(mention.normalized_query_terms)
    if len(mention.raw_text) <= 16 or not matched_features:
        return None
    return " ".join(matched_features)
