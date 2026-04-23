"""
创建时间: 2026-04-23
任务: level3-mention-retrieval
说明: 覆盖描述性人物 mention 抽取、query 构造与 provider 级 metadata 标记。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.mention_extraction import extract_person_mentions
from src.rag.mention_query import build_mention_evidence_queries
from src.rag.retriever import DisambigContextProvider
from src.storage.repositories.chunk import SimilarChunkRow


def test_extract_person_mentions_captures_descriptive_person_mentions() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: 初版规则应能覆盖衣着/外貌/动作组合的匿名人物指代。
    """
    mentions = extract_person_mentions("那个穿红衣的女子突然出手。门口的老者没有说话。")

    raw_texts = [mention.raw_text for mention in mentions]
    assert "穿红衣的女子" in raw_texts
    assert "门口的老者" in raw_texts
    red_woman = next(mention for mention in mentions if mention.raw_text == "穿红衣的女子")
    assert red_woman.mention_type == "feature_action"
    assert red_woman.cues["role_word"] == "女子"
    assert "红衣" in red_woman.cues["appearance"]
    assert "出手" in red_woman.cues["action"]


def test_build_mention_evidence_queries_builds_variants() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: mention query 应保留原文片段，并补充线索词组合变体。
    """
    mentions = extract_person_mentions("那个穿红衣的女子突然出手。")
    queries = build_mention_evidence_queries(mentions)

    query_texts = [query.query_text for query in queries]
    assert "穿红衣的女子" in query_texts
    assert "红衣 女子 出手" in query_texts
    assert any(query.mention_text == "穿红衣的女子" for query in queries)


def test_build_mention_evidence_queries_skips_broad_pronoun_role_mentions() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-review-fix
    说明: 纯“那个少女/那名女子”缺少可区分线索，初版不应生成过宽 Level3 query。
    """
    mentions = extract_person_mentions("那个少女回头看了一眼。")

    assert [mention.raw_text for mention in mentions] == ["那个少女"]
    assert mentions[0].mention_type == "pronoun_role"
    assert build_mention_evidence_queries(mentions) == []


def test_build_mention_evidence_queries_keeps_action_or_location_mentions() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-review-fix
    说明: 有动作或位置线索的描述性 mention 仍应进入 Level3 query。
    """
    mentions = extract_person_mentions("那名女子低声开口。门口的老者没有说话。")
    queries = build_mention_evidence_queries(mentions)

    query_texts = [query.query_text for query in queries]
    assert "那名女子" in query_texts
    assert "女子 开口 低声" in query_texts
    assert "门口的老者" in query_texts
    assert "门口 老者" in query_texts


def test_build_semantic_recall_items_records_mention_metadata_only_for_mention_rows() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: mention 级增强只写 metadata，不改变 semantic_recall 的 evidence_type。
    """
    items = EvidenceBundleBuilder().build_semantic_recall_items(
        [
            SimilarChunkRow(
                chunk_id=2,
                text="红衣女子收剑而立。",
                similarity=0.91,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子", "出手"),
            ),
            SimilarChunkRow(chunk_id=3, text="普通 chunk 召回。", similarity=0.83),
        ]
    )

    assert items[0].evidence_type == "semantic_recall"
    assert items[0].metadata["query_kind"] == "mention"
    assert items[0].metadata["mention_text"] == "穿红衣的女子"
    assert items[0].metadata["matched_features"] == ["红衣", "女子", "出手"]
    assert items[0].metadata["evidence_granularity"] == "chunk"
    assert items[0].metadata["rerank_method"] == "chunk_embedding"
    assert "query_kind" not in items[1].metadata


def test_build_emotion_exemplar_items_ignores_mention_rows() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-review-fix
    说明: mention 级身份召回不能污染 Phase1 情绪 exemplar 证据。
    """
    items = EvidenceBundleBuilder().build_emotion_exemplar_items(
        [
            SimilarChunkRow(
                chunk_id=2,
                text="红衣女子收剑而立。",
                similarity=0.91,
                emotional_valence="mild_negative",
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子", "出手"),
            ),
            SimilarChunkRow(
                chunk_id=3,
                text="她抿唇不语，袖口攥得发白。",
                similarity=0.88,
                emotional_valence="mild_negative",
            ),
        ]
    )

    assert len(items) == 1
    assert items[0].metadata["chunk_id"] == 3


@pytest.mark.asyncio
async def test_provider_collects_mention_queries_and_dedupes_results() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: provider 应执行 mention query 并按 chunk_id 去重，同时保留 mention metadata。
    """
    provider = DisambigContextProvider(level3_enabled=True, level3_top_k=2)
    provider._level3.is_available = MagicMock(return_value=True)
    provider._level3.search_similar_chunks = AsyncMock(
        side_effect=[
            [SimilarChunkRow(chunk_id=5, text="白芷曾穿红衣出手。", similarity=0.94)],
            [SimilarChunkRow(chunk_id=5, text="白芷曾穿红衣出手。", similarity=0.90)],
            [SimilarChunkRow(chunk_id=6, text="相似场景。", similarity=0.88)],
        ]
    )

    mention_queries = build_mention_evidence_queries(extract_person_mentions("那个穿红衣的女子突然出手。"))[:2]
    bundle = await provider.collect_evidence_with_level3(
        context_text="那个穿红衣的女子突然出手。",
        max_chunk_id=9,
        mention_queries=mention_queries,
    )

    semantic_items = [item for item in bundle.semantic_evidence if item.evidence_type == "semantic_recall"]
    assert [item.metadata["chunk_id"] for item in semantic_items] == [5, 6]
    assert semantic_items[0].metadata["query_kind"] == "mention"
    assert semantic_items[0].metadata["mention_text"] == "穿红衣的女子"
    assert provider._level3.search_similar_chunks.await_args_list[0].kwargs["max_chunk_id"] == 9
