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
            alias_mappings=[AliasMapping(alias="白老板", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )

    blocks = render_annotation_prompt_blocks(bundle)

    assert blocks.level1_facts is not None
    assert blocks.disambig_context is not None
    assert "已确认别名：白老板 -> 白芷" in blocks.disambig_context
    assert "已确认实体：白芷 (character)" in blocks.disambig_context
    assert "「蒙面人」可能是：白芷" in blocks.disambig_context


class FakeChunkRepository:
    def __init__(self, _conn) -> None:
        pass

    def fetch_prev_chunk_text(self, run_id: str, chunk_id: int) -> str:
        return f"prev:{run_id}:{chunk_id}"

    def fetch_next_chunk_text(self, run_id: str, chunk_id: int) -> str:
        return f"next:{run_id}:{chunk_id}"


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
    provider.collect_evidence.return_value = bundle

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entities_prompt_from_authority",
        lambda *_args, **_kwargs: "【近期活跃角色】\n- 白芷（helper）：观察 [chunk=12]",
    )
    monkeypatch.setattr(context_module, "_extract_names_from_text", lambda _text: ["蒙面人"])

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=12,
        chunk_text="蒙面人出现了",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=provider,
        run_id="run-1",
    )

    assert context.prev_chunk_text == "prev:run-1:12"
    assert context.next_chunk_text == "next:run-1:12"
    assert context.prompt_active_entities == "【近期活跃角色】\n- 白芷（helper）：观察 [chunk=12]"
    assert context.evidence_bundle is bundle
    assert context.prompt_disambig_context is not None
    assert "「蒙面人」可能是：白芷" in context.prompt_disambig_context


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
    provider.collect_evidence.return_value = bundle
    expected_active_entities = render_annotation_prompt_blocks(bundle).active_entities

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entities_prompt_from_authority",
        lambda *_args, **_kwargs: "【近期活跃角色】\n- 旧值（helper）：观察 [chunk=19]",
    )
    monkeypatch.setattr(context_module, "_extract_names_from_text", lambda _text: ["陆明"])

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=20,
        chunk_text="陆明再次出现",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=provider,
        run_id="run-override",
    )

    assert expected_active_entities is not None
    assert context.prompt_active_entities == expected_active_entities
    assert context.prev_chunk_text == "prev:run-override:20"
    assert context.next_chunk_text == "next:run-override:20"


def test_prepare_chunk_context_skips_context_loading_when_disabled(monkeypatch):
    build_authority_prompt = Mock(return_value="不应被调用")
    monkeypatch.setattr(context_module, "_build_active_entities_prompt_from_authority", build_authority_prompt)

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=5,
        chunk_text="无上下文增强",
        alias_map={},
        use_context_enhancement=False,
        disambig_provider=None,
        run_id="run-disabled",
    )

    build_authority_prompt.assert_not_called()
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities is None
    assert context.evidence_bundle is None


def test_prepare_chunk_context_skips_context_loading_when_run_id_missing(monkeypatch):
    build_authority_prompt = Mock(return_value="不应被调用")
    monkeypatch.setattr(context_module, "_build_active_entities_prompt_from_authority", build_authority_prompt)

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=6,
        chunk_text="缺少 run_id",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=None,
        run_id=None,
    )

    build_authority_prompt.assert_not_called()
    assert context.prev_chunk_text is None
    assert context.next_chunk_text is None
    assert context.prompt_active_entities is None
    assert context.evidence_bundle is None


def test_prepare_chunk_context_without_disambig_provider_keeps_authority_context(monkeypatch):
    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entities_prompt_from_authority",
        lambda *_args, **_kwargs: "【近期活跃角色】\n- 苏镜（protagonist）：思考 [chunk=9]",
    )

    context = _prepare_chunk_context(
        conn=object(),
        chunk_id=9,
        chunk_text="苏镜独自思考",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=None,
        run_id="run-authority-only",
    )

    assert context.prev_chunk_text == "prev:run-authority-only:9"
    assert context.next_chunk_text == "next:run-authority-only:9"
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
    provider.requires_level3.return_value = False
    provider.is_level3_available.return_value = False
    provider.collect_evidence.return_value = bundle

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entities_prompt_from_authority",
        lambda *_args, **_kwargs: "【近期活跃角色】\n- 陆明（helper）：巡查 [chunk=18]",
    )
    monkeypatch.setattr(context_module, "_extract_names_from_text", lambda _text: ["黑衣人"])

    context = await _prepare_chunk_context_with_level3(
        conn=object(),
        chunk_id=18,
        chunk_text="黑衣人现身",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=provider,
        run_id="run-async",
    )

    assert context.prev_chunk_text == "prev:run-async:18"
    assert context.next_chunk_text == "next:run-async:18"
    assert context.prompt_active_entities == "【近期活跃角色】\n- 陆明（helper）：巡查 [chunk=18]"
    assert context.evidence_bundle is bundle
    assert context.prompt_disambig_context is not None
    assert "「黑衣人」可能是：陆明" in context.prompt_disambig_context


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_uses_semantic_collection_when_available(monkeypatch):
    bundle = EvidenceBundle(
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
    )
    provider = Mock()
    provider.requires_level3.return_value = False
    provider.is_level3_available.return_value = True
    provider.collect_evidence_with_level3 = AsyncMock(return_value=bundle)
    expected_active_entities = render_annotation_prompt_blocks(bundle).active_entities

    monkeypatch.setattr("src.storage.repositories.ChunkRepository", FakeChunkRepository)
    monkeypatch.setattr(
        context_module,
        "_build_active_entities_prompt_from_authority",
        lambda *_args, **_kwargs: "【近期活跃角色】\n- 旧值（helper）：观察 [chunk=20]",
    )
    monkeypatch.setattr(context_module, "_extract_names_from_text", lambda _text: ["程霜"])

    context = await _prepare_chunk_context_with_level3(
        conn=object(),
        chunk_id=21,
        chunk_text="程霜翻阅旧案卷",
        alias_map={},
        use_context_enhancement=True,
        disambig_provider=provider,
        run_id="run-level3-available",
    )

    provider.collect_evidence_with_level3.assert_awaited_once_with(
        names_in_chunk=["程霜"],
        current_chunk=21,
        context_text="程霜翻阅旧案卷",
        exclude_chunk_ids=[21],
    )
    assert expected_active_entities is not None
    assert context.prompt_active_entities == expected_active_entities
    assert context.prompt_vector_evidence is not None
    assert "[Chunk 4]" in context.prompt_vector_evidence


@pytest.mark.asyncio
async def test_prepare_chunk_context_with_level3_raises_when_required_but_unavailable(monkeypatch):
    provider = Mock()
    provider.requires_level3.return_value = True
    provider.is_level3_available.return_value = False
    monkeypatch.setattr(context_module, "_extract_names_from_text", lambda _text: ["程霜"])

    with pytest.raises(RuntimeError, match="Level 3 vector retrieval is required but not available"):
        await _prepare_chunk_context_with_level3(
            conn=object(),
            chunk_id=30,
            chunk_text="程霜追查旧线索",
            alias_map={},
            use_context_enhancement=False,
            disambig_provider=provider,
            run_id=None,
        )
