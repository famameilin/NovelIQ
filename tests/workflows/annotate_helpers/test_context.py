"""
创建时间: 2026-04-12
创建者: TraeAI
任务: 用户请求创建 ChunkContext 测试
说明: 测试 ChunkContext.evidence_bundle 字段和遗留兼容字段

修改时间: 2026-04-17
修改者: Codex
任务: trim-legacy-string-evidence
修改内容: 删除依赖遗留字符串字段的测试，改为仅测试主链路 prompt_* 入口和 annotation_prompt_blocks
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.config import settings
from src.knowledge.authority import (
    ActiveEntityContext,
    AliasMapping,
    CanonicalEntity,
    EntityTypeFact,
    Level1AuthoritySnapshot,
)
from src.models.local.annotation.evidence_renderer import render_annotation_prompt_blocks
from src.rag.evidence_types import EvidenceBundle, EvidenceItem
from src.workflows.annotate_helpers import context as context_module
from src.workflows.annotate_helpers.context import (
    ChunkContext,
    _build_active_entities_prompt_from_authority,
    _build_optional_task_model_client,
    _collect_requested_names,
    _collect_seed_entities,
    _init_evidence_service,
    _prepare_chunk_context,
    _prepare_chunk_context_with_level3,
)


def test_chunk_context_has_evidence_bundle():
    bundle = EvidenceBundle(
        structured_evidence=[],
        local_evidence=[],
        semantic_evidence=[],
    )
    context = ChunkContext(evidence_bundle=bundle)
    assert context.evidence_bundle is not None
    assert isinstance(context.evidence_bundle, EvidenceBundle)


def test_chunk_context_all_fields_default_none():
    context = ChunkContext()
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.evidence_bundle is None
    assert context.annotation_prompt_blocks is None
    assert context.active_entities_fallback is None
    assert context.prompt_active_entities is None
    assert context.prompt_disambig_context is None
    assert context.prompt_vector_evidence is None


def test_chunk_context_prompt_active_entities_prefers_renderer_blocks():
    context = ChunkContext(
        annotation_prompt_blocks=render_annotation_prompt_blocks(
            EvidenceBundle(
                local_evidence=[
                    EvidenceItem(
                        evidence_type="active_entity",
                        source="level2",
                        content="程霜",
                        metadata={"name": "程霜", "role": "helper", "recent_action": "追查", "last_seen_chunk": 21},
                    ),
                ],
            )
        ),
    )
    assert context.prompt_active_entities is not None
    assert "程霜" in context.prompt_active_entities


def test_chunk_context_prompt_active_entities_uses_fallback_when_no_renderer():
    context = ChunkContext(active_entities_fallback="authority-fallback")
    assert context.prompt_active_entities == "authority-fallback"


def test_chunk_context_prompt_disambig_context_from_renderer():
    context = ChunkContext(
        annotation_prompt_blocks=render_annotation_prompt_blocks(
            EvidenceBundle(
                local_evidence=[
                    EvidenceItem(
                        evidence_type="disambig_candidate",
                        source="level2",
                        content="「灰衣人」可能是：程霜",
                    ),
                ],
                requested_names=["灰衣人"],
            )
        ),
    )
    assert context.prompt_disambig_context is not None
    assert "「灰衣人」可能是：程霜" in context.prompt_disambig_context


def test_chunk_context_prompt_disambig_context_none_when_empty():
    context = ChunkContext()
    assert context.prompt_disambig_context is None


def test_chunk_context_prompt_vector_evidence_from_renderer():
    context = ChunkContext(
        annotation_prompt_blocks=render_annotation_prompt_blocks(
            EvidenceBundle(
                semantic_evidence=[
                    EvidenceItem(
                        evidence_type="vector_evidence",
                        source="level3",
                        content="程霜在旧案卷中发现了线索。",
                        chunk_id=4,
                        score=0.91,
                    )
                ],
            )
        ),
    )
    assert context.prompt_vector_evidence is not None
    assert "[Chunk 4]" in context.prompt_vector_evidence


def test_chunk_context_prompt_vector_evidence_none_when_empty():
    context = ChunkContext()
    assert context.prompt_vector_evidence is None


def test_chunk_context_renderer_blocks_take_priority_over_fallback():
    context = ChunkContext(
        active_entities_fallback="old-fallback",
        annotation_prompt_blocks=render_annotation_prompt_blocks(
            EvidenceBundle(
                local_evidence=[
                    EvidenceItem(
                        evidence_type="active_entity",
                        source="level2",
                        content="程霜",
                        metadata={"name": "程霜", "role": "helper", "recent_action": "追查", "last_seen_chunk": 21},
                    ),
                ],
            )
        ),
    )
    assert "程霜" in context.prompt_active_entities
    assert "old-fallback" not in context.prompt_active_entities


def test_chunk_context_evidence_bundle_with_structured_evidence():
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(evidence_type="alias_mapping", source="level1", content="张三 → 张三丰"),
        ],
        local_evidence=[],
        semantic_evidence=[],
    )

    context = ChunkContext(evidence_bundle=bundle)

    assert context.evidence_bundle is not None
    assert len(context.evidence_bundle.structured_evidence) == 1
    assert context.evidence_bundle.structured_evidence[0].evidence_type == "alias_mapping"


def test_build_active_entities_prompt_from_authority_uses_authority_contract(monkeypatch):
    service = Mock()
    service.build_active_entity_view.return_value = [
        ActiveEntityContext(
            name="白芷",
            entity_id=7,
            role="helper",
            entity_type="organization",
            status="active",
            last_seen_chunk=12,
            recent_action="观察",
            recent_emotion="平静",
        )
    ]

    mocked_factory = Mock(return_value=service)
    monkeypatch.setattr(
        "src.workflows.annotate_helpers.context.KnowledgeGraphAuthorityService.from_session",
        mocked_factory,
    )

    rendered = _build_active_entities_prompt_from_authority(
        conn=object(),
        run_id="run-1",
        chunk_id=12,
        lookback=5,
    )

    mocked_factory.assert_called_once()
    service.build_active_entity_view.assert_called_once_with("run-1", current_chunk=12, lookback=5)
    assert rendered is not None
    assert "【近期活跃角色】" in rendered
    assert "白芷" in rendered
    assert "[chunk=12]" in rendered


def test_build_active_entities_prompt_from_authority_returns_none_without_active_entities(monkeypatch):
    service = Mock()
    service.build_active_entity_view.return_value = []

    monkeypatch.setattr(
        "src.workflows.annotate_helpers.context.KnowledgeGraphAuthorityService.from_session",
        Mock(return_value=service),
    )

    rendered = _build_active_entities_prompt_from_authority(
        conn=object(),
        run_id="run-empty",
        chunk_id=3,
        lookback=5,
    )

    assert rendered is None


def test_render_annotation_prompt_blocks_includes_level1_facts_in_main_disambig_context():
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content="白芷",
                metadata={"name": "白芷"},
            )
        ],
        requested_names=["蒙面人"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="蒙面人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )

    blocks = render_annotation_prompt_blocks(bundle)

    assert blocks.level1_facts is not None
    assert blocks.disambig_context is not None
    assert "已确认别名：蒙面人 -> 白芷" in blocks.disambig_context
    assert "已确认实体：白芷 (character)" in blocks.disambig_context


def test_collect_seed_entities_only_keeps_aliases_explicitly_mentioned_in_current_chunk():
    """
    创建时间: 2026-04-25
    任务: fix-phase-seed-entity-scope
    说明: alias_map 是整轮累计状态，seed_entities 只能保留当前 chunk 明确提到的 alias/canonical，
          不能把无关历史别名一并带进本轮 Level3 request。
    """
    seed_entities = _collect_seed_entities(
        {"小七": "程霜", "老刀": "韩山"},
        ["白芷"],
        query_text="小七跟着白芷翻阅旧案卷。",
    )

    assert seed_entities == ["小七", "程霜", "白芷"]


def test_collect_seed_entities_keeps_canonical_when_chunk_mentions_canonical_directly():
    """
    创建时间: 2026-04-25
    任务: fix-phase-seed-entity-scope
    说明: 若 chunk 直接提到 canonical，本轮只需带 canonical 本身；
          不应因为 alias_map 存在就把同 canonical 的其他历史 alias 全量注入。
    """
    seed_entities = _collect_seed_entities(
        {"小七": "程霜", "老刀": "韩山"},
        [],
        query_text="程霜翻阅旧案卷，神色不动。",
    )

    assert seed_entities == ["程霜"]


def test_collect_requested_names_promotes_direct_canonical_mentions_only_when_explicitly_present():
    """
    创建时间: 2026-04-26
    任务: fix-direct-canonical-requested-names
    说明: `requested_names` 可以从可信候选中补 canonical 直出现，
          但只能提升正文里真的出现的名字，不能把背景名字整包抬成当前 consumer target。
    """
    requested_names = _collect_requested_names(
        {},
        query_text="程霜翻阅旧案卷，韩山没有出场。",
        extra_names=["程霜", "白芷"],
    )

    assert requested_names == ["程霜"]


class FailOnChunkRepository:
    def __init__(self, _conn) -> None:
        raise AssertionError(
            "Phase2 current-text-only path should not instantiate "
            "ChunkRepository for prev/next chunk text"
        )


def test_prepare_chunk_context_preserves_authority_active_entities_when_level2_bundle_has_none(monkeypatch):
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「蒙面人」可能是：白芷",
            )
        ],
        requested_names=["蒙面人"],
    )
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[bundle, EvidenceBundle()])

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="白芷",
                entity_id=7,
                role="helper",
                recent_action="观察",
                recent_emotion=None,
                last_seen_chunk=12,
            )
        ],
    )

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=12,
        chunk_text="蒙面人出现了",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-1",
    )

    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities == "【近期活跃角色】\n- 白芷（helper）：观察 [chunk=12]"
    assert context.evidence_bundle is bundle
    assert context.phase2_bundle is None
    assert context.prompt_disambig_context is not None
    assert "「蒙面人」可能是：白芷" in context.prompt_disambig_context
    assert provider.collect.await_count == 1
    assert provider.collect.await_args_list[0].args[0].consumer == "annotation_phase1"
    assert context.phase4_request_template is not None
    assert context.phase4_request_template.requested_names == []
    assert context.phase4_request_template.seed_entities == []


def test_prepare_chunk_context_overrides_authority_active_entities_when_level2_bundle_has_value(monkeypatch):
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content="陆明",
                metadata={
                    "name": "陆明",
                    "role": "helper",
                    "recent_action": "巡查",
                    "last_seen_chunk": 20,
                },
            )
        ]
    )
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[bundle, EvidenceBundle()])
    expected_active_entities = render_annotation_prompt_blocks(bundle).active_entities

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="旧值",
                entity_id=9,
                role="helper",
                recent_action="观察",
                recent_emotion=None,
                last_seen_chunk=19,
            )
        ],
    )

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=20,
        chunk_text="陆明再次出现",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-override",
    )

    assert expected_active_entities is not None
    assert context.prompt_active_entities == expected_active_entities
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert provider.collect.await_count == 1


def test_prepare_chunk_context_can_collect_phase2_evidence_when_opted_in(monkeypatch):
    """
    创建时间: 2026-04-26
    修改时间: 2026-04-26
    修改者: Codex
    任务: phase2-strong-foreshadowing
    修改内容: 补充 targeted ablation 回归，确认显式打开 include_phase2_evidence 后，
    同步上下文构建仍会恢复 Phase2 evidence 收集。
    """
    phase1_bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「蒙面人」可能是：白芷",
            )
        ]
    )
    phase2_bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「黑衣人」可能是：陆明",
            )
        ]
    )
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[phase1_bundle, phase2_bundle])

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="白芷",
                entity_id=7,
                role="helper",
                recent_action="观察",
                recent_emotion=None,
                last_seen_chunk=12,
            )
        ],
    )
    monkeypatch.setattr(settings.analysis.multi_phase_annotation, "include_phase2_evidence", True)

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=12,
        chunk_text="蒙面人出现了",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-1",
    )

    assert context.phase1_bundle is phase1_bundle
    assert context.phase2_bundle is phase2_bundle
    assert provider.collect.await_count == 2
    assert provider.collect.await_args_list[1].args[0].consumer == "annotation_phase2"


def test_prepare_chunk_context_skips_context_loading_when_disabled(monkeypatch):
    build_authority_contexts = Mock(return_value=[])
    monkeypatch.setattr(context_module, "_build_active_entity_contexts_from_authority", build_authority_contexts)

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=5,
        chunk_text="无上下文增强",
        alias_map={},
        use_context_enhancement=False,
        evidence_service=None,
        run_id="run-disabled",
    )

    build_authority_contexts.assert_not_called()
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities is None
    assert context.evidence_bundle is None


def test_prepare_chunk_context_skips_context_loading_when_run_id_missing(monkeypatch):
    build_authority_contexts = Mock(return_value=[])
    monkeypatch.setattr(context_module, "_build_active_entity_contexts_from_authority", build_authority_contexts)

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=6,
        chunk_text="缺少 run_id",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=None,
        run_id=None,
    )

    build_authority_contexts.assert_not_called()
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities is None
    assert context.evidence_bundle is None


def test_prepare_chunk_context_without_disambig_provider_keeps_authority_context(monkeypatch):
    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="苏镜",
                entity_id=3,
                role="protagonist",
                recent_action="思考",
                recent_emotion=None,
                last_seen_chunk=9,
            )
        ],
    )

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=9,
        chunk_text="苏镜独自思考",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=None,
        run_id="run-authority-only",
    )

    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities == "【近期活跃角色】\n- 苏镜（protagonist）：思考 [chunk=9]"
    assert context.evidence_bundle is None
    assert context.prompt_disambig_context is None
    assert context.prompt_vector_evidence is None


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_preserves_authority_active_entities_when_level2_bundle_has_none(
    monkeypatch,
):
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「黑衣人」可能是：陆明",
            )
        ],
        requested_names=["黑衣人"],
    )
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[bundle, bundle])

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="陆明",
                entity_id=11,
                role="helper",
                recent_action="巡查",
                recent_emotion=None,
                last_seen_chunk=18,
            )
        ],
    )

    context = await _prepare_chunk_context_with_level3(
        conn=object(),
        chunk_id=18,
        chunk_text="黑衣人现身",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-async",
    )

    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities == "【近期活跃角色】\n- 陆明（helper）：巡查 [chunk=18]"
    assert context.evidence_bundle is bundle
    assert context.phase2_bundle is None
    assert context.prompt_disambig_context is not None
    assert "「黑衣人」可能是：陆明" in context.prompt_disambig_context
    assert provider.collect.await_count == 2
    phase1_request = provider.collect.await_args_list[0].args[0]
    assert phase1_request.consumer == "annotation_phase1"
    assert phase1_request.requested_names == []
    assert phase1_request.seed_entities == ["陆明"]
    phase3_request = provider.collect.await_args_list[1].args[0]
    assert phase3_request.consumer == "annotation_phase3"


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_uses_semantic_collection_when_available(monkeypatch):
    phase1_bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content="程霜",
                metadata={
                    "name": "程霜",
                    "role": "helper",
                    "recent_action": "追查",
                    "last_seen_chunk": 21,
                },
            )
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="程霜在旧案卷中发现了线索。",
                chunk_id=4,
                score=0.91,
                metadata={"text": "程霜在旧案卷中发现了线索。", "similarity": 0.91},
            )
        ],
        requested_names=["程霜"],
    )
    phase1_bundle.semantic_evidence.append(
        EvidenceItem(
            evidence_type="emotion_exemplar",
            source="chunk_embeddings",
            content="她翻阅旧案卷时指节发白。",
            chunk_id=7,
            score=0.88,
            metadata={
                "chunk_id": 7,
                "text": "她翻阅旧案卷时指节发白。",
                "similarity": 0.88,
                "emotional_valence": "mild_negative",
            },
        )
    )
    phase3_bundle = EvidenceBundle(
        semantic_evidence=[
            EvidenceItem(
                evidence_type="vector_evidence",
                source="level3",
                content="程霜在旧案卷中发现了线索。",
                chunk_id=4,
                score=0.91,
                metadata={"text": "程霜在旧案卷中发现了线索。", "similarity": 0.91},
            )
        ],
    )
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[phase1_bundle, phase3_bundle])

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="旧值",
                entity_id=12,
                role="helper",
                recent_action="观察",
                recent_emotion=None,
                last_seen_chunk=20,
            )
        ],
    )

    context = await _prepare_chunk_context_with_level3(
        conn=object(),
        chunk_id=21,
        chunk_text="程霜翻阅旧案卷",
        alias_map={"小七": "程霜", "老刀": "韩山"},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-level3-available",
    )

    assert provider.collect.await_count == 2
    phase1_request = provider.collect.await_args_list[0].args[0]
    phase3_request = provider.collect.await_args_list[1].args[0]
    assert phase1_request.consumer == "annotation_phase1"
    assert phase1_request.objective == "identity"
    assert phase1_request.requested_names == ["程霜"]
    assert phase1_request.seed_entities == ["程霜", "旧值"]
    assert phase3_request.consumer == "annotation_phase3"
    assert phase3_request.requested_names == ["程霜"]
    assert phase3_request.seed_entities == ["程霜", "旧值"]
    assert context.phase1_bundle is phase1_bundle
    assert context.phase2_bundle is None
    assert context.phase3_bundle is phase3_bundle
    assert any(item.evidence_type == "emotion_exemplar" for item in context.phase1_bundle.semantic_evidence)
    assert context.phase4_request_template is not None
    assert context.phase4_request_template.consumer == "annotation_phase4"
    assert context.phase4_request_template.objective == "relation"
    assert context.phase4_request_template.requested_names == []
    assert context.phase4_request_template.seed_entities == []
    expected_blocks = render_annotation_prompt_blocks(context.phase1_bundle)
    assert expected_blocks.active_entities is not None
    assert context.prompt_active_entities == expected_blocks.active_entities
    assert context.prompt_disambig_context is not None
    assert "<Emotion_Exemplars>" in context.prompt_disambig_context
    assert context.prompt_vector_evidence is not None
    assert "[Chunk 4]" in context.prompt_vector_evidence


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_promotes_direct_canonical_mentions_into_requested_names(monkeypatch):
    """
    创建时间: 2026-04-26
    修改时间: 2026-04-26
    修改者: Codex
    任务: fix-direct-canonical-requested-names
    说明: 当正文直接出现 canonical 名且它来自可信 active-entity 上下文时，
          Phase1/Phase3 request 都应把它写入 requested_names，而不是只留在 seed_entities。
    """
    provider = Mock()
    provider.collect = AsyncMock(side_effect=[EvidenceBundle(), EvidenceBundle()])

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FailOnChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entity_contexts_from_authority",
        lambda *_args, **_kwargs: [
            ActiveEntityContext(
                name="程霜",
                entity_id=12,
                role="helper",
                recent_action="追查",
                recent_emotion=None,
                last_seen_chunk=20,
            )
        ],
    )

    await _prepare_chunk_context_with_level3(
        conn=object(),
        chunk_id=21,
        chunk_text="程霜翻阅旧案卷。",
        alias_map={},
        use_context_enhancement=True,
        evidence_service=provider,
        run_id="run-canonical-name",
    )

    assert provider.collect.await_count == 2
    phase1_request = provider.collect.await_args_list[0].args[0]
    phase3_request = provider.collect.await_args_list[1].args[0]
    assert phase1_request.requested_names == ["程霜"]
    assert phase1_request.seed_entities == ["程霜"]
    assert phase3_request.requested_names == ["程霜"]
    assert phase3_request.seed_entities == ["程霜"]


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_raises_when_required_but_unavailable(monkeypatch):
    provider = Mock()
    provider.collect = AsyncMock(side_effect=RuntimeError("Level 3 vector retrieval is required but not available"))

    with pytest.raises(RuntimeError, match="Level 3 vector retrieval is required but not available"):
        await _prepare_chunk_context_with_level3(
            conn=object(),
            chunk_id=30,
            chunk_text="程霜追查旧线索",
            alias_map={},
            use_context_enhancement=False,
            evidence_service=provider,
            run_id=None,
        )


def test_build_optional_task_model_client_returns_none_when_config_absent():
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: mention/rerank 未配置时应保持禁用，不创建伪客户端去污染现有规则/确定性主链。
    """
    assert (
        _build_optional_task_model_client(
            "mention_extraction",
            enabled=False,
            novel_id="novel-x",
            session=object(),
            run_id=None,
        )
        is None
    )
    assert (
        _build_optional_task_model_client(
            "level3_rerank",
            enabled=False,
            novel_id="novel-x",
            session=object(),
            run_id=None,
        )
        is None
    )


def test_build_optional_task_model_client_raises_on_incomplete_config(monkeypatch):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: 可选增强模型一旦配置半截，就应立刻报错，不能静默退回导致用户误以为已启用。
    """
    monkeypatch.setattr(settings.rag, "mention_extraction_enabled", True)
    monkeypatch.setattr(settings.models.mention_extraction, "base_url", "http://localhost:9000")
    monkeypatch.setattr(settings.models.mention_extraction, "model", None)

    with pytest.raises(RuntimeError, match="optional task model config incomplete"):
        _build_optional_task_model_client(
            "mention_extraction",
            enabled=settings.rag.mention_extraction_enabled,
            novel_id="novel-x",
            session=object(),
            run_id="run-1",
        )


def test_build_optional_task_model_client_raises_when_enabled_but_config_absent(monkeypatch):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: rag 开关显式启用后，若模型配置完全缺失，应直接报错，避免“以为开了其实没跑”。
    """
    monkeypatch.setattr(settings.rag, "level3_rerank_enabled", True)
    monkeypatch.setattr(settings.models.level3_rerank, "base_url", None)
    monkeypatch.setattr(settings.models.level3_rerank, "model", None)
    monkeypatch.setattr(settings.models.level3_rerank, "api_key", None)
    monkeypatch.setattr(settings.models.level3_rerank, "timeout_s", None)

    with pytest.raises(RuntimeError, match="optional task model enabled but config is absent"):
        _build_optional_task_model_client(
            "level3_rerank",
            enabled=settings.rag.level3_rerank_enabled,
            novel_id="novel-x",
            session=object(),
            run_id="run-1",
        )


def test_build_optional_task_model_client_injects_token_usage_callback(monkeypatch):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-audit
    说明: 可选增强模型接入主链后，也应注入统一 token_usage callback，
          避免 mention extraction / rerank 请求成功却完全不进账本。
    """

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            self.runtime_context = None

        def set_runtime_context(self, novel_id, token_usage_callback) -> None:
            self.runtime_context = (novel_id, token_usage_callback)

    monkeypatch.setattr(settings.rag, "mention_extraction_enabled", True)
    monkeypatch.setattr(settings.models.mention_extraction, "base_url", "http://localhost:9000")
    monkeypatch.setattr(settings.models.mention_extraction, "model", "mention-model")
    monkeypatch.setattr("src.models.local.base.BaseModelClient", FakeClient)

    client = _build_optional_task_model_client(
        "mention_extraction",
        enabled=settings.rag.mention_extraction_enabled,
        novel_id="novel-x",
        session=object(),
        run_id="run-1",
    )

    assert isinstance(client, FakeClient)
    assert client.runtime_context is not None
    assert client.runtime_context[0] == "novel-x"
    assert callable(client.runtime_context[1])


def test_init_evidence_service_injects_optional_mention_and_rerank_clients(monkeypatch):
    """
    创建时间: 2026-04-24
    任务: llm-mention-rerank-chain
    说明: mention extraction / model rerank 配置完整时，provider 初始化应把两条增强链都接进来。
    """

    class FakeProvider:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_mention_extractor = object()
    fake_level3_reranker = object()
    fake_embedding_client = object()

    monkeypatch.setattr(settings.rag, "mention_extraction_enabled", True)
    monkeypatch.setattr(settings.rag, "level3_rerank_enabled", True)
    monkeypatch.setattr(settings.models.mention_extraction, "base_url", "http://localhost:9001")
    monkeypatch.setattr(settings.models.mention_extraction, "model", "mention-model")
    monkeypatch.setattr(settings.models.level3_rerank, "base_url", "http://localhost:9002")
    monkeypatch.setattr(settings.models.level3_rerank, "model", "rerank-model")
    monkeypatch.setattr("src.storage.repositories.GraphRepository", lambda conn: "graph-repo")
    monkeypatch.setattr("src.models.local.embedding.EmbeddingClient", lambda novel_id: fake_embedding_client)
    monkeypatch.setattr(context_module, "_init_optional_mention_extractor", lambda **kwargs: fake_mention_extractor)
    monkeypatch.setattr(context_module, "_init_optional_level3_reranker", lambda **kwargs: fake_level3_reranker)
    monkeypatch.setattr("src.rag.NarrativeEvidenceService", FakeProvider)

    provider = _init_evidence_service(
        conn=object(),
        novel_id="novel-x",
        use_context=True,
        run_id="run-1",
    )

    assert isinstance(provider, FakeProvider)
    assert provider.kwargs["mention_extractor"] is fake_mention_extractor
    assert provider.kwargs["level3_reranker"] is fake_level3_reranker
    assert provider.kwargs["embedding_client"] is fake_embedding_client
