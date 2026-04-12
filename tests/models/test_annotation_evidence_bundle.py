from __future__ import annotations

from src.models.local.annotation.messages import _build_annotation_messages_v2
from src.rag import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)


def test_annotation_messages_prefers_evidence_bundle_rendering() -> None:
    bundle = EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="graph_alias_map",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
            )
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content="白芷",
                metadata={
                    "name": "白芷",
                    "role": "other",
                    "last_action": "观察",
                    "last_emotion": "平静",
                    "chunk_id": 12,
                },
            )
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="chunk_embeddings",
                content="灰衣人抬手露出袖中银针。",
                metadata={
                    "chunk_id": 5,
                    "similarity": 0.92,
                    "text": "灰衣人抬手露出袖中银针。",
                },
            )
        ],
        requested_names=["灰衣人"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷")],
            confirmed_relations=[ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )

    messages = _build_annotation_messages_v2(
        text="灰衣人站在门口。",
        chunk_id=12,
        evidence_bundle=bundle,
    )

    user_message = messages[-1]["content"]
    assert "灰衣人 → 白芷" in user_message
    assert "【近期活跃角色】" in user_message
    assert "白芷" in user_message
    assert "<Vector_Evidence>" in user_message


def test_annotation_messages_keep_explicit_strings_over_bundle() -> None:
    bundle = EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="graph_active_entities",
                content="白芷",
                metadata={"name": "白芷"},
            )
        ]
    )

    messages = _build_annotation_messages_v2(
        text="灰衣人站在门口。",
        active_entities="EXPLICIT_ACTIVE",
        disambig_context="EXPLICIT_DISAMBIG",
        evidence_bundle=bundle,
    )

    user_message = messages[-1]["content"]
    assert "EXPLICIT_ACTIVE" in user_message
    assert "EXPLICIT_DISAMBIG" in user_message


def test_annotation_messages_prefer_explicit_alias_map_over_bundle() -> None:
    bundle = EvidenceBundle(
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
        )
    )

    messages = _build_annotation_messages_v2(
        text="灰衣人站在门口。",
        alias_map={"黑衣客": "白芷"},
        evidence_bundle=bundle,
    )

    user_message = messages[-1]["content"]
    assert "黑衣客 → 白芷" in user_message
    assert "灰衣人 → 白芷" not in user_message
