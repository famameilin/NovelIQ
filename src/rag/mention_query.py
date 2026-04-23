"""
Level3 mention query 构造。

创建时间: 2026-04-23
任务: level3-mention-retrieval
说明: 将描述性人物 mention 转换为可复用的向量检索 query 变体。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.rag.mention_extraction import PersonMention


@dataclass(frozen=True, slots=True)
class MentionEvidenceQuery:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 单条 mention 检索 query，携带可写入 EvidenceItem.metadata 的来源信息。
    """

    query_text: str
    mention_text: str
    mention_type: str
    matched_features: tuple[str, ...]


def _as_string_list(value: object) -> list[str]:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 统一读取 PersonMention.cues 中的字符串列表字段，避免下游使用下标或隐式类型假设。
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
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 为每个 mention 构造“原文片段”和“线索词组合”两类 query，初版保持保守且可回归。
    """
    queries: list[MentionEvidenceQuery] = []
    seen_query_texts: set[str] = set()

    for mention in mentions:
        appearance = _as_string_list(mention.cues.get("appearance"))
        actions = _as_string_list(mention.cues.get("action"))
        role_words = _as_string_list(mention.cues.get("role_word"))
        matched_features = tuple(dict.fromkeys(appearance + role_words + actions))

        variants = [mention.raw_text]
        compact_features = " ".join(matched_features)
        if compact_features and compact_features != mention.raw_text:
            variants.append(compact_features)
        if actions:
            variants.append(f"{mention.raw_text} {' '.join(actions)}")

        for query_text in variants:
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
                )
            )

    return queries
