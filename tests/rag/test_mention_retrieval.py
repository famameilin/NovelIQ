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
from src.rag.mention_rerank import rerank_mention_level3_results
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


def test_extract_person_mentions_keeps_action_cues_local_to_current_mention() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-mention-local-cue-scope
    说明: 多人物共句时，后一个人物的动作不能误绑到前一个 mention 上，避免生成错误 query 特征。
    """
    mentions = extract_person_mentions("门口的老者没有说话，那名女子低声开口。")

    old_man = next(mention for mention in mentions if mention.raw_text == "门口的老者")
    woman = next(mention for mention in mentions if mention.raw_text == "那名女子")

    assert old_man.mention_type == "location_role"
    assert old_man.cues["action"] == []
    assert woman.mention_type == "action_role"
    assert woman.cues["action"] == ["开口", "低声"]


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
    assert items[0].chunk_id == 2
    assert items[0].score == 0.91
    assert items[1].metadata["query_kind"] == "chunk"
    assert items[1].metadata["mention_text"] is None
    assert items[1].metadata["matched_features"] == []
    assert items[1].metadata["chunk_semantic_score"] == 0.83
    assert items[1].chunk_id == 3
    assert items[1].score == 0.83


def test_build_semantic_recall_items_freezes_rerank_metadata_contract() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-mention-retrieval-closure
    说明: mention-aware rerank 已进入收口阶段，semantic_recall metadata 应稳定暴露 query/rerank/paragraph 字段，
          便于后续日志与延期评测直接复用。
    """
    item = EvidenceBundleBuilder().build_semantic_recall_items(
        [
            SimilarChunkRow(
                chunk_id=7,
                text="白芷正是那名红衣女子。",
                similarity=0.95,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子", "出手"),
                local_preview="红衣女子回头看向众人。",
                paragraph_index=2,
                paragraph_semantic_score=0.95,
                paragraph_local_start_char=18,
                paragraph_local_end_char=31,
                paragraph_global_start_char=318,
                paragraph_global_end_char=331,
                chunk_semantic_score=0.82,
                business_rerank_score=1.11,
                final_rank_score=1.11,
                feature_overlap=("红衣", "女子"),
                active_entity_bonus=0.06,
                identity_clue_bonus=0.05,
                candidate_related_bonus=0.05,
                time_decay=0.04,
                rerank_penalty=0.0,
                penalties=(),
            )
        ]
    )[0]

    assert item.metadata["query_kind"] == "mention"
    assert item.metadata["mention_text"] == "穿红衣的女子"
    assert item.metadata["mention_type"] == "feature_action"
    assert item.metadata["matched_features"] == ["红衣", "女子", "出手"]
    assert item.metadata["feature_overlap"] == ["红衣", "女子"]
    assert item.metadata["local_preview"] == "红衣女子回头看向众人。"
    assert item.metadata["paragraph_index"] == 2
    assert item.metadata["chunk_semantic_score"] == 0.82
    assert item.metadata["paragraph_semantic_score"] == 0.95
    assert item.metadata["business_rerank_score"] == 1.11
    assert item.metadata["final_rank_score"] == 1.11
    assert item.metadata["paragraph_local_start_char"] == 18
    assert item.metadata["paragraph_global_start_char"] == 318
    assert item.score == 1.11
    assert item.metadata["business_rerank_method"] == "mention_feature_rerank"


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


def test_build_emotion_exemplar_items_uses_chunk_semantic_score_after_paragraph_rerank() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-emotion-exemplar-score-contract
    说明: paragraph rerank 只影响 semantic_recall；emotion exemplar 仍应按 chunk 级相似度排序和打分。
    """
    items = EvidenceBundleBuilder().build_emotion_exemplar_items(
        [
            SimilarChunkRow(
                chunk_id=8,
                text="她说话时指尖微颤，眼底发冷。",
                similarity=0.97,
                chunk_semantic_score=0.83,
                emotional_valence="mild_negative",
                local_preview="她眼底发冷。",
                paragraph_index=1,
            ),
            SimilarChunkRow(
                chunk_id=9,
                text="他只是点了点头，语气却更冷。",
                similarity=0.88,
                emotional_valence="mild_negative",
            ),
        ]
    )

    assert [item.metadata["chunk_id"] for item in items] == [9, 8]
    assert items[0].score == 0.88
    assert items[1].score == 0.83
    assert items[1].metadata["similarity"] == 0.83
    assert items[1].content == "她说话时指尖微颤，眼底发冷。"


def test_mention_rerank_promotes_feature_consistent_history() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: 低一点的向量分若有更多 mention 特征、候选名和身份线索，应能排到纯相似场景前面。
    """
    reranked = rerank_mention_level3_results(
        [
            SimilarChunkRow(
                chunk_id=18,
                text="厅中有人争执，气氛同样紧张。",
                similarity=0.90,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子", "出手"),
            ),
            SimilarChunkRow(
                chunk_id=12,
                text="白芷正是那名红衣女子，曾在门前突然出手。",
                similarity=0.82,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子", "出手"),
            ),
        ],
        active_entity_names={"白芷"},
        candidate_names={"白芷"},
        current_chunk=20,
    )

    assert [row.chunk_id for row in reranked] == [12, 18]
    assert reranked[0].business_rerank_score is not None
    assert reranked[0].final_rank_score == reranked[0].business_rerank_score
    assert reranked[0].chunk_semantic_score == 0.82
    assert reranked[0].feature_overlap == ("红衣", "女子", "出手")
    assert reranked[0].active_entity_bonus > 0
    assert reranked[0].identity_clue_bonus > 0


def test_mention_rerank_uses_local_preview_only_when_paragraph_preview_exists() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-mention-rerank-visible-evidence-only
    说明: paragraph rerank 已选中 local_preview 时，mention rerank 只能依据这段可见局部证据加权，
          不能再偷看完整 chunk 里未展示的候选名或身份揭示句。
    """
    reranked = rerank_mention_level3_results(
        [
            SimilarChunkRow(
                chunk_id=12,
                text="白芷正是那名红衣女子，众人这才认出她的身份。",
                similarity=0.85,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子"),
                local_preview="她站在门外，没有开口。",
                paragraph_index=1,
            ),
            SimilarChunkRow(
                chunk_id=18,
                text="相似场景，但没有身份信息。",
                similarity=0.86,
                query_kind="mention",
                mention_text="穿红衣的女子",
                mention_type="feature_action",
                matched_features=("红衣", "女子"),
                local_preview="她站在门外，没有开口。",
                paragraph_index=0,
            ),
        ],
        active_entity_names={"白芷"},
        candidate_names={"白芷"},
        current_chunk=20,
    )

    hidden_clue_row = next(row for row in reranked if row.chunk_id == 12)
    assert hidden_clue_row.feature_overlap == ()
    assert hidden_clue_row.active_entity_bonus == 0.0
    assert hidden_clue_row.identity_clue_bonus == 0.0
    assert hidden_clue_row.candidate_related_bonus == 0.0
    assert [row.chunk_id for row in reranked] == [18, 12]


@pytest.mark.asyncio
async def test_provider_collects_mention_queries_and_dedupes_results() -> None:
    """
    创建时间: 2026-04-23
    任务: level3-mention-retrieval
    说明: provider 应执行 mention query 并按 chunk_id 去重，同时保留 mention metadata。
    """
    provider = DisambigContextProvider(level3_enabled=True, level3_top_k=2)
    provider._level3.is_available = MagicMock(return_value=True)
    provider._level3.ensure_level3_ready = AsyncMock(return_value=None)
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
    assert semantic_items[0].metadata["business_rerank_method"] == "mention_feature_rerank"
    assert semantic_items[0].metadata["final_rank_score"] == semantic_items[0].score
    assert semantic_items[0].metadata["business_rerank_score"] >= semantic_items[0].metadata["chunk_semantic_score"]
    assert provider._level3.search_similar_chunks.await_args_list[0].kwargs["max_chunk_id"] == 9
    assert provider._level3.search_similar_chunks.await_args_list[0].kwargs["top_k"] == 20
    assert all(call.kwargs["ensure_ready"] is False for call in provider._level3.search_similar_chunks.await_args_list)


@pytest.mark.asyncio
async def test_provider_reranks_before_prompt_budget_cutoff() -> None:
    """
    创建时间: 2026-04-24
    任务: level3-mention-rerank
    说明: provider 应先扩大召回池并 rerank，再裁剪回 prompt top_k，避免只按向量分保留相似场景。
    """
    provider = DisambigContextProvider(level3_enabled=True, level3_top_k=1)
    provider._level3.is_available = MagicMock(return_value=True)
    provider._level3.ensure_level3_ready = AsyncMock(return_value=None)
    provider._level3.search_similar_chunks = AsyncMock(
        side_effect=[
            [
                SimilarChunkRow(
                    chunk_id=4,
                    text="白芷正是那名红衣女子，她随后突然出手。",
                    similarity=0.82,
                ),
                SimilarChunkRow(chunk_id=5, text="众人同时看向门外，场景相似。", similarity=0.91),
            ],
            [],
        ]
    )

    mention_queries = build_mention_evidence_queries(extract_person_mentions("那个穿红衣的女子突然出手。"))[:1]
    bundle = await provider.collect_evidence_with_level3(
        names_in_chunk=["白芷"],
        current_chunk=6,
        context_text="那个穿红衣的女子突然出手。",
        max_chunk_id=5,
        mention_queries=mention_queries,
    )

    semantic_items = [item for item in bundle.semantic_evidence if item.evidence_type == "semantic_recall"]
    assert [item.metadata["chunk_id"] for item in semantic_items] == [4]
    assert semantic_items[0].metadata["chunk_semantic_score"] == 0.82
    assert semantic_items[0].metadata["final_rank_score"] == semantic_items[0].score
    assert semantic_items[0].metadata["feature_overlap"] == ["红衣", "女子", "出手"]
    assert provider._level3.search_similar_chunks.await_args_list[0].kwargs["top_k"] == 20
