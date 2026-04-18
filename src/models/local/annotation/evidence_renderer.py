from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models.local.evidence_renderer_shared import (
    render_shared_evidence_sections,
    select_shared_evidence_sections,
)

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


@dataclass(slots=True)
class AnnotationPromptBlocks:
    level1_facts: str | None = None
    active_entities: str | None = None
    disambig_context: str | None = None
    vector_evidence: str | None = None


def render_annotation_alias_map_text(
    *,
    alias_map: dict[str, str] | None = None,
    evidence_bundle: EvidenceBundle | None = None,
) -> str:
    alias_rows: list[tuple[str, str]] = []

    if alias_map is not None:
        alias_rows.extend(alias_map.items())
    elif evidence_bundle is not None:
        alias_rows.extend(evidence_bundle.structured_alias_map().items())

    canonical_to_aliases: dict[str, list[str]] = {}
    for alias, canonical in alias_rows:
        if not alias or not canonical or alias == canonical:
            continue
        canonical_to_aliases.setdefault(canonical, [])
        if alias not in canonical_to_aliases[canonical]:
            canonical_to_aliases[canonical].append(alias)

    if not canonical_to_aliases:
        return "{}"

    lines = []
    for canonical, aliases in canonical_to_aliases.items():
        alias_str = "、".join(aliases)
        lines.append(f"- {alias_str} → {canonical}")
    return "\n".join(lines)


def render_annotation_evidence_blocks(bundle: EvidenceBundle) -> list[str]:
    """将 EvidenceBundle 渲染为 Phase 2 可消费的结构化证据块列表。"""
    shared_sections = render_shared_evidence_sections(bundle)
    return select_shared_evidence_sections(
        shared_sections,
        ("structured_evidence", "disambig_candidates", "vector_evidence"),
    )


def render_annotation_prompt_blocks(
    bundle: EvidenceBundle,
    *,
    include_level1_alias_mappings: bool = True,
) -> AnnotationPromptBlocks:
    shared_sections = render_shared_evidence_sections(
        bundle,
        include_level1_alias_mappings=include_level1_alias_mappings,
    )
    prompt_sections = select_shared_evidence_sections(
        shared_sections,
        ("level1_facts", "disambig_candidates", "vector_evidence"),
    )
    # 中文注释：annotation 主 prompt 当前只接收 active_entities + disambig_context 两个入口，
    # 因此这里显式把 Level 1 结构化事实并入 disambig_context，保证稳定事实真正进入主链路。
    combined_disambig = "\n\n".join(prompt_sections) if prompt_sections else None

    return AnnotationPromptBlocks(
        level1_facts=shared_sections.level1_facts,
        active_entities=shared_sections.active_entities,
        disambig_context=combined_disambig,
        vector_evidence=shared_sections.vector_evidence,
    )


def render_relation_extraction_evidence_sections(
    evidence_bundle: EvidenceBundle | None,
) -> list[str]:
    """渲染 Phase 4 关系抽取可消费的共享证据区段。"""

    if evidence_bundle is None:
        return []

    shared_sections = render_shared_evidence_sections(evidence_bundle)
    # 中文注释：Phase4 只选择稳定事实、局部活跃实体和历史语义召回三类 section；
    # 不把消歧候选或 raw structured block 带进去，避免把候选身份和重复事实噪音注入关系抽取。
    return select_shared_evidence_sections(
        shared_sections,
        ("level1_facts", "active_entities", "vector_evidence"),
    )


def render_dialogue_attribution_evidence_sections(
    evidence_bundle: EvidenceBundle | None,
    *,
    alias_map: dict[str, str] | None = None,
    active_entities: str | None = None,
) -> list[str]:
    """渲染 Phase 3 对话归属可消费的共享证据区段。"""

    if evidence_bundle is None and active_entities is None:
        return []

    shared_sections = (
        render_shared_evidence_sections(
            evidence_bundle,
            include_level1_alias_mappings=alias_map is None,
        )
        if evidence_bundle is not None
        else None
    )

    sections: list[str] = []
    # 中文注释：active_entities 属于任务侧输入，不属于 EvidenceBundle 本体；
    # 如果上游已经给出带 fallback 的活跃实体上下文，就优先沿用，不再让 renderer 从 bundle 反推覆盖它。
    # 显式传入空字符串时，表示调用方要抑制该区段；这时也不应再回退 bundle 里的活跃实体。
    if active_entities is not None:
        if active_entities:
            sections.append(active_entities)
    elif shared_sections and shared_sections.active_entities:
        sections.append(shared_sections.active_entities)

    if shared_sections:
        sections.extend(
            select_shared_evidence_sections(
                shared_sections,
                ("level1_facts", "disambig_candidates", "vector_evidence"),
            )
        )
    return sections
