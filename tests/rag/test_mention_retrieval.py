"""
创建时间: 2026-04-23
任务: level3-mention-retrieval
说明: 覆盖描述性人物 mention 抽取、query 构造与 provider 级 metadata 标记。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rag.evidence_bundle_builder import EvidenceBundleBuilder
from src.rag.mention_extraction import extract_person_mentions
from src.rag.mention_extraction_llm import (
    LLMPersonMentionCloudItem,
    LLMPersonMentionCloudResponse,
    LLMPersonMentionExtractor,
    LLMPersonMentionItem,
    LLMPersonMentionResponse,
    normalize_mention_response,
)
from src.rag.mention_extraction_service import MentionExtractionService
from src.rag.mention_extraction_types import MentionExtractionRequest, PersonMention
from src.rag.mention_query import build_mention_evidence_queries
from src.rag.mention_rerank import rerank_mention_level3_results
from src.rag.model_rerank import Level3RerankResult
from src.rag.model_rerank_llm import LLMLevel3Reranker, LLMLevel3RerankItem, LLMLevel3RerankResponse
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


def test_build_mention_evidence_queries_uses_llm_compressed_terms() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM mention 输出 normalized_query_terms 时，应额外生成 mention_compressed query 供 embedding 检索。
    """
    mention = PersonMention(
        raw_text="一直跟在侯飞白身后的瘦高男子",
        mention_type="descriptive_person",
        sentence_text="一直跟在侯飞白身后的瘦高男子忽然停下。",
        cues={"role_word": "男子", "appearance": ["瘦高"], "action": ["跟在身后"]},
        normalized_query_terms=("瘦高", "男子", "跟在身后"),
        source="llm",
        confidence=0.91,
    )

    queries = build_mention_evidence_queries([mention])
    compressed = next(query for query in queries if query.query_variant == "mention_compressed")

    assert compressed.query_text == "瘦高 男子 跟在身后"
    assert compressed.mention_source == "llm"
    assert compressed.mention_confidence == 0.91


@pytest.mark.asyncio
async def test_mention_extraction_service_uses_llm_then_normalizes() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: service 应优先采用 LLM mention，并过滤纯实名与不在原文中的幻觉 mention。
    """
    extractor = MagicMock()
    extractor.extract_mentions = AsyncMock(
        return_value=[
            PersonMention(
                raw_text="袖口绣银线的那人",
                mention_type="descriptive_person",
                sentence_text="袖口绣银线的那人站在船头。",
                cues={"appearance": ["袖口绣银线"], "role_word": "那人"},
                source="llm",
            ),
            PersonMention(
                raw_text="侯飞白",
                mention_type="name",
                sentence_text="侯飞白也在场。",
                cues={},
                source="llm",
            ),
            PersonMention(
                raw_text="不存在的黑衣人",
                mention_type="descriptive_person",
                sentence_text="不存在的黑衣人拔剑。",
                cues={"appearance": ["黑衣"]},
                source="llm",
            ),
        ]
    )

    service = MentionExtractionService(extractor)
    mentions = await service.extract_mentions(
        MentionExtractionRequest(
            text="袖口绣银线的那人站在船头。",
            names_in_chunk=("侯飞白",),
        )
    )

    assert [mention.raw_text for mention in mentions] == ["袖口绣银线的那人"]
    assert mentions[0].source == "llm"


@pytest.mark.asyncio
async def test_mention_extraction_service_falls_back_to_rule_extractor() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM extractor 抛错时不能静默失败，应回退规则 extractor 并继续产出可用 mention。
    """
    extractor = MagicMock()
    extractor.extract_mentions = AsyncMock(side_effect=RuntimeError("model down"))

    service = MentionExtractionService(extractor)
    mentions = await service.extract_mentions(
        MentionExtractionRequest(text="那个穿红衣的女子突然出手。")
    )

    assert [mention.raw_text for mention in mentions] == ["穿红衣的女子"]
    assert mentions[0].source == "rule"


@pytest.mark.asyncio
async def test_llm_person_mention_extractor_uses_cloud_safe_schema_for_cloud_api() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-mention-cloud-schema
    说明: 云端 strict schema 不接受动态 cues dict 时，应切换到 cloud-safe response model，
          并在返回后归一化回内部 PersonMention.cues 合同。
    """
    model_client = MagicMock()
    model_client.is_cloud_api = MagicMock(return_value=True)
    model_client._config = MagicMock(timeout_s=30, model="mention-model")
    model_client._session = object()
    model_client._call_api = AsyncMock(
        return_value=LLMPersonMentionCloudResponse(
            mentions=[
                LLMPersonMentionCloudItem(
                    raw_text="袖口绣银线的那人",
                    mention_type="descriptive_person",
                    sentence_text="袖口绣银线的那人站在船头。",
                    role_word="那人",
                    appearance=["袖口绣银线"],
                    action=["站在船头"],
                    location=["船头"],
                    confidence=0.88,
                    normalized_query_terms=["袖口绣银线", "那人", "船头"],
                )
            ]
        )
    )
    extractor = LLMPersonMentionExtractor(model_client)

    with patch("src.rag.model_call_audit.record_model_interaction") as mock_record_model_interaction:
        mentions = await extractor.extract_mentions(
            MentionExtractionRequest(
                text="袖口绣银线的那人站在船头。",
                names_in_chunk=("侯飞白",),
                run_id="run-1",
                current_chunk=17,
            )
        )

    assert model_client._call_api.await_args.kwargs["response_model"] is LLMPersonMentionCloudResponse
    assert model_client._call_api.await_args.kwargs["raw_response_format"] == {"type": "json_object"}
    assert [mention.raw_text for mention in mentions] == ["袖口绣银线的那人"]
    assert mentions[0].cues["role_word"] == "那人"
    assert mentions[0].cues["appearance"] == ["袖口绣银线"]
    assert mentions[0].cues["action"] == ["站在船头"]
    assert mentions[0].cues["location"] == ["船头"]
    assert mentions[0].normalized_query_terms == ("袖口绣银线", "那人", "船头")
    assert model_client._record_estimated_token_usage_from_messages.called
    assert mock_record_model_interaction.call_args.kwargs["interaction_type"] == "mention_extraction"
    assert mock_record_model_interaction.call_args.kwargs["run_id"] == "run-1"
    assert mock_record_model_interaction.call_args.kwargs["chunk_id"] == 17


def test_normalize_mention_response_keeps_local_schema_contract() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-mention-cloud-schema
    说明: 本地 schema 与云端 schema 归一化后都应产出同一份内部 PersonMention 合同。
    """
    local_mentions = normalize_mention_response(
        LLMPersonMentionResponse(
            mentions=[
                LLMPersonMentionItem(
                    raw_text="门口的老者",
                    mention_type="location_role",
                    sentence_text="门口的老者没有说话。",
                    cues={
                        "role_word": "老者",
                        "appearance": [],
                        "action": [],
                        "location": ["门口"],
                    },
                    normalized_query_terms=["门口", "老者"],
                )
            ]
        )
    )

    assert [mention.raw_text for mention in local_mentions] == ["门口的老者"]
    assert local_mentions[0].cues["role_word"] == "老者"
    assert local_mentions[0].cues["location"] == ["门口"]


@pytest.mark.asyncio
async def test_llm_level3_reranker_keeps_highest_score_for_duplicate_chunk_ids() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: LLM rerank 若异常返回重复 chunk_id，应保留最高分结果，避免 provider 被重复低分覆盖。
    """
    model_client = MagicMock()
    model_client._config = MagicMock(timeout_s=30, model="rerank-model")
    model_client.is_cloud_api = MagicMock(return_value=False)
    model_client._session = object()
    model_client._call_api = AsyncMock(
        return_value=LLMLevel3RerankResponse(
            results=[
                LLMLevel3RerankItem(chunk_id=7, model_rerank_score=0.71),
                LLMLevel3RerankItem(chunk_id=7, model_rerank_score=0.93, model_rerank_reason="局部证据更聚焦"),
                LLMLevel3RerankItem(chunk_id=8, model_rerank_score=0.65),
            ]
        )
    )
    reranker = LLMLevel3Reranker(model_client)

    with patch("src.rag.model_call_audit.record_model_interaction") as mock_record_model_interaction:
        results = await reranker.rerank(
            query_text="那个穿红衣的女子突然出手。",
            candidates=[
                MagicMock(
                    chunk_id=7,
                    mention_text="穿红衣的女子",
                    candidate_chunk_text="白芷正是那名红衣女子。",
                    candidate_local_preview="红衣女子回头看向众人。",
                    chunk_semantic_score=0.81,
                    paragraph_semantic_score=0.95,
                    business_rerank_score=1.03,
                ),
                MagicMock(
                    chunk_id=8,
                    mention_text="穿红衣的女子",
                    candidate_chunk_text="相似场景。",
                    candidate_local_preview="众人看向门外。",
                    chunk_semantic_score=0.84,
                    paragraph_semantic_score=0.86,
                    business_rerank_score=0.9,
                ),
            ],
            run_id="run-1",
            chunk_id=23,
        )

    score_by_chunk = {item.chunk_id: item for item in results}
    assert score_by_chunk[7].model_rerank_score == 0.93
    assert score_by_chunk[7].model_rerank_reason == "局部证据更聚焦"
    assert score_by_chunk[8].model_rerank_score == 0.65
    assert model_client._record_estimated_token_usage_from_messages.called
    assert mock_record_model_interaction.call_args.kwargs["interaction_type"] == "level3_rerank"
    assert mock_record_model_interaction.call_args.kwargs["run_id"] == "run-1"
    assert mock_record_model_interaction.call_args.kwargs["chunk_id"] == 23


@pytest.mark.asyncio
async def test_llm_person_mention_extractor_records_error_audit_when_call_fails() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-audit
    说明: mention extraction 调用失败时，也应留下 error 审计记录，并补记估算 token。
    """
    model_client = MagicMock()
    model_client.is_cloud_api = MagicMock(return_value=True)
    model_client._config = MagicMock(timeout_s=30, model="mention-model")
    model_client._session = object()
    model_client._call_api = AsyncMock(side_effect=RuntimeError("provider down"))
    extractor = LLMPersonMentionExtractor(model_client)

    with patch("src.rag.model_call_audit.record_model_interaction") as mock_record_model_interaction:
        with pytest.raises(RuntimeError, match="provider down"):
            await extractor.extract_mentions(
                MentionExtractionRequest(
                    text="门口那个灰衣人没有说话。",
                    run_id="run-err",
                    current_chunk=9,
                )
            )

    model_client._record_estimated_token_usage_from_messages.assert_called_once()
    assert mock_record_model_interaction.call_args.kwargs["status"] == "error"
    assert mock_record_model_interaction.call_args.kwargs["run_id"] == "run-err"
    assert mock_record_model_interaction.call_args.kwargs["chunk_id"] == 9


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


def test_extract_person_mentions_captures_bare_compound_role_mentions() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-bare-compound-mention-extraction
    说明: 文档基线将“灰衣人/黑衣人”列为核心 case，裸露复合角色词也应进入 mention query。
    """
    mentions = extract_person_mentions("灰衣人立在门口。黑衣人忽然出手。")
    queries = build_mention_evidence_queries(mentions)

    raw_texts = [mention.raw_text for mention in mentions]
    query_texts = [query.query_text for query in queries]

    assert raw_texts == ["灰衣人", "黑衣人"]
    assert [mention.mention_type for mention in mentions] == ["appearance_based", "feature_action"]
    assert "灰衣人" in query_texts
    assert "黑衣人" in query_texts
    assert "黑衣 黑衣人 出手" in query_texts


def test_extract_person_mentions_dedupes_demonstrative_compound_role_subspans() -> None:
    """
    创建时间: 2026-04-24
    任务: fix-bare-compound-mention-extraction
    说明: “那个灰衣人”已由指示词规则命中时，不应再额外抽取重叠子串“灰衣人”。
    """
    mentions = extract_person_mentions("那个灰衣人立在门口。")

    assert [mention.raw_text for mention in mentions] == ["那个灰衣人"]


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
async def test_provider_builds_mention_queries_inside_provider() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: workflow 不传 mention_queries 时，provider 应自己抽取 mention、构造 query 并写入新 metadata。
    """
    provider = DisambigContextProvider(level3_enabled=True, level3_top_k=2)
    provider._level3.is_available = MagicMock(return_value=True)
    provider._level3.ensure_level3_ready = AsyncMock(return_value=None)
    provider._level3.search_similar_chunks = AsyncMock(
        side_effect=[
            [SimilarChunkRow(chunk_id=5, text="白芷曾穿红衣出手。", similarity=0.94)],
            [SimilarChunkRow(chunk_id=6, text="红衣女子立在门前。", similarity=0.90)],
            [],
            [],
        ]
    )

    bundle = await provider.collect_evidence_with_level3(
        names_in_chunk=["白芷"],
        current_chunk=9,
        context_text="那个穿红衣的女子突然出手。",
        max_chunk_id=8,
    )

    semantic_items = [item for item in bundle.semantic_evidence if item.evidence_type == "semantic_recall"]
    assert semantic_items[0].metadata["query_kind"] == "mention"
    assert semantic_items[0].metadata["mention_source"] == "rule"
    assert semantic_items[0].metadata["query_variant"] == "mention_raw"
    assert semantic_items[0].metadata["rerank_source"] == "deterministic_fallback"
    assert provider._level3.search_similar_chunks.await_args_list[0].args[0] == "穿红衣的女子"


@pytest.mark.asyncio
async def test_provider_uses_model_rerank_when_available() -> None:
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 模型 rerank 可用时应覆盖最终排序分，同时保留 deterministic business_rerank_score 作为观察字段。
    """
    reranker = MagicMock()
    reranker.rerank = AsyncMock(
        return_value=[
            Level3RerankResult(chunk_id=11, model_rerank_score=0.97, model_rerank_reason="局部证据更一致"),
            Level3RerankResult(chunk_id=10, model_rerank_score=0.81),
        ]
    )
    provider = DisambigContextProvider(level3_enabled=True, level3_top_k=2, level3_reranker=reranker)
    provider._level3.is_available = MagicMock(return_value=True)
    provider._level3.ensure_level3_ready = AsyncMock(return_value=None)
    provider._level3.search_similar_chunks = AsyncMock(
        side_effect=[
            [
                SimilarChunkRow(chunk_id=10, text="红衣女子出手。", similarity=0.95),
                SimilarChunkRow(chunk_id=11, text="白芷正是那名红衣女子。", similarity=0.88),
            ],
            [],
        ]
    )

    mention_queries = build_mention_evidence_queries(extract_person_mentions("那个穿红衣的女子突然出手。"))[:1]
    bundle = await provider.collect_evidence_with_level3(
        names_in_chunk=["白芷"],
        current_chunk=12,
        context_text="那个穿红衣的女子突然出手。",
        max_chunk_id=11,
        mention_queries=mention_queries,
    )

    semantic_items = [item for item in bundle.semantic_evidence if item.evidence_type == "semantic_recall"]
    assert [item.metadata["chunk_id"] for item in semantic_items] == [11, 10]
    assert semantic_items[0].metadata["model_rerank_score"] == 0.97
    assert semantic_items[0].metadata["model_rerank_enabled"] is True
    assert semantic_items[0].metadata["rerank_source"] == "model"
    assert semantic_items[0].metadata["business_rerank_score"] is not None
    assert semantic_items[0].score == 0.97
    reranker.rerank.assert_awaited_once()


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
