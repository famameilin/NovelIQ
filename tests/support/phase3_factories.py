from __future__ import annotations

from src.rag.evidence_types import EvidenceBundle, EvidenceItem


def build_phase3_bundle() -> EvidenceBundle:
    """构造 Phase3 对话归属共享证据。"""
    return EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
            ),
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content="白芷",
                metadata={"name": "白芷", "entity_type": "character"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={
                    "name": "白芷",
                    "role": "speaker_candidate",
                    "recent_action": "按住剑柄",
                    "recent_emotion": "警惕",
                    "last_seen_chunk": 12,
                },
            ),
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「灰衣人」可能是：白芷",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="灰衣人忽然压低声音。",
                metadata={
                    "chunk_id": 5,
                    "similarity": 0.91,
                    "text": "灰衣人忽然压低声音。",
                },
            )
        ],
        requested_names=["灰衣人"],
    )


def build_phase3_overflow_bundle() -> EvidenceBundle:
    """构造超过渲染上限的 evidence bundle，用来锁定证据裁剪规则。"""
    structured = [
        EvidenceItem(
            evidence_type="alias_mapping",
            source="level1",
            content=f"别名{i} -> 人物{i}",
            metadata={"alias": f"别名{i}", "canonical": f"人物{i}"},
        )
        for i in range(1, 4)
    ]
    structured.extend(
        [
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content=f"人物{i}",
                metadata={"name": f"人物{i}", "entity_type": "character"},
            )
            for i in range(1, 4)
        ]
    )
    structured.extend(
        [
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content=f"人物{i}<盟友>人物{i + 1}",
                metadata={
                    "from_name": f"人物{i}",
                    "to_name": f"人物{i + 1}",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            )
            for i in range(1, 4)
        ]
    )

    local = [
        EvidenceItem(
            evidence_type="active_entity",
            source="level2",
            content=f"人物{i}",
            metadata={
                "name": f"人物{i}",
                "role": "speaker_candidate",
                "recent_action": f"动作{i}",
                "recent_emotion": f"情绪{i}",
                "last_seen_chunk": 20 - i,
            },
        )
        for i in range(1, 5)
    ]
    local.extend(
        [
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content=f"「别名{i}」可能是：人物{i}",
            )
            for i in range(1, 4)
        ]
    )

    semantic = [
        EvidenceItem(
            evidence_type="semantic_recall",
            source="level3",
            content=f"人物{i}历史片段：" + ("甲" * 150),
            metadata={
                "chunk_id": i,
                "similarity": 0.9 - i * 0.01,
                "text": f"人物{i}历史片段：" + ("甲" * 150),
            },
        )
        for i in range(1, 4)
    ]

    return EvidenceBundle(
        structured_evidence=structured,
        local_evidence=local,
        semantic_evidence=semantic,
        requested_names=["别名1", "别名2", "别名3"],
    )


def build_phase3_priority_bundle() -> EvidenceBundle:
    """构造可验证候选优先级的证据。"""
    return EvidenceBundle(
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物一",
                metadata={"name": "人物一"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物二",
                metadata={"name": "人物二"},
            ),
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="人物三",
                metadata={"name": "人物三"},
            ),
        ],
        requested_names=["别名一", "别名二", "别名三"],
    )
