from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models.local.evidence_renderer_shared import (
    render_disambig_candidates,
    render_vector_evidence,
)

if TYPE_CHECKING:
    from src.knowledge.authority import Level1AuthoritySnapshot
    from src.rag.evidence_types import EvidenceBundle, EvidenceItem


@dataclass(slots=True)
class AnnotationPromptBlocks:
    level1_facts: str | None = None
    active_entities: str | None = None
    disambig_context: str | None = None
    vector_evidence: str | None = None


def _render_active_entity_lines(items: list[EvidenceItem]) -> str | None:
    if not items:
        return None

    lines = ["【近期活跃角色】"]
    for item in items:
        name = str(item.metadata.get("name", item.content))
        role = str(item.metadata.get("role") or "other")
        last_action = str(item.metadata.get("recent_action") or item.metadata.get("last_action") or "")
        last_emotion = str(item.metadata.get("recent_emotion") or item.metadata.get("last_emotion") or "")
        chunk_id = item.metadata.get("last_seen_chunk", item.metadata.get("chunk_id"))

        detail_parts = [part for part in [last_action, last_emotion] if part]
        detail = "；".join(detail_parts) if detail_parts else "（无近期动作）"
        if chunk_id is not None:
            lines.append(f"- {name}（{role}）：{detail} [chunk={chunk_id}]")
        else:
            lines.append(f"- {name}（{role}）：{detail}")
    return "\n".join(lines)


def _append_unique_line(bucket: list[str], seen_lines: set[str], line: str) -> None:
    if line not in seen_lines:
        bucket.append(line)
        seen_lines.add(line)


def _collect_level1_lines_from_structured(
    bundle: EvidenceBundle,
    *,
    include_alias_mappings: bool = True,
) -> list[str]:
    alias_lines: list[str] = []
    entity_lines: list[str] = []
    relation_lines: list[str] = []
    seen_lines: set[str] = set()
    entity_types: dict[str, str] = {}

    for item in bundle.structured_evidence:
        if item.evidence_type == "entity_type":
            name = str(item.metadata.get("name", "")).strip()
            entity_type = str(item.metadata.get("entity_type", "")).strip()
            if name and entity_type:
                entity_types[name] = entity_type

    for item in bundle.structured_evidence:
        if item.evidence_type == "alias_mapping":
            if not include_alias_mappings:
                continue
            alias = str(item.metadata.get("alias", "")).strip()
            canonical = str(item.metadata.get("canonical", "")).strip()
            if alias and canonical:
                _append_unique_line(alias_lines, seen_lines, f"- 已确认别名：{alias} -> {canonical}")
        elif item.evidence_type == "canonical_entity":
            name = str(item.metadata.get("name", item.content)).strip()
            entity_type = entity_types.get(name) or str(item.metadata.get("entity_type", "")).strip()
            type_suffix = f" ({entity_type})" if entity_type else ""
            if name:
                _append_unique_line(entity_lines, seen_lines, f"- 已确认实体：{name}{type_suffix}")
        elif item.evidence_type == "confirmed_relation":
            if item.metadata.get("is_active") is False:
                continue
            from_name = str(item.metadata.get("from_name", "")).strip()
            to_name = str(item.metadata.get("to_name", "")).strip()
            relation_type = str(item.metadata.get("relation_type", "")).strip()
            if from_name and to_name and relation_type:
                _append_unique_line(
                    relation_lines,
                    seen_lines,
                    f"- 已确认关系：{from_name} -{relation_type}-> {to_name}",
                )

    return alias_lines + entity_lines + relation_lines


def _collect_level1_lines_from_snapshot(
    snapshot: Level1AuthoritySnapshot,
    *,
    include_alias_mappings: bool = True,
) -> list[str]:
    alias_lines: list[str] = []
    entity_lines: list[str] = []
    relation_lines: list[str] = []
    seen_lines: set[str] = set()
    entity_types = {
        item.name.strip(): item.entity_type.strip() for item in snapshot.entity_types if item.name and item.entity_type
    }

    if include_alias_mappings:
        for mapping in snapshot.alias_mappings:
            alias = mapping.alias.strip()
            canonical = mapping.canonical.strip()
            if alias and canonical:
                _append_unique_line(alias_lines, seen_lines, f"- 已确认别名：{alias} -> {canonical}")

    for entity in snapshot.canonical_entities:
        name = entity.name.strip()
        if not name:
            continue
        entity_type = entity_types.get(name, entity.entity_type.strip())
        type_suffix = f" ({entity_type})" if entity_type else ""
        _append_unique_line(entity_lines, seen_lines, f"- 已确认实体：{name}{type_suffix}")

    for relation in snapshot.confirmed_relations:
        if not relation.is_active:
            continue
        from_name = relation.from_name.strip()
        to_name = relation.to_name.strip()
        relation_type = relation.relation_type.strip()
        if from_name and to_name and relation_type:
            _append_unique_line(relation_lines, seen_lines, f"- 已确认关系：{from_name} -{relation_type}-> {to_name}")

    return alias_lines + entity_lines + relation_lines


def _render_annotation_level1(
    bundle: EvidenceBundle,
    *,
    include_alias_mappings: bool = True,
) -> str | None:
    lines = (
        _collect_level1_lines_from_structured(bundle, include_alias_mappings=include_alias_mappings)
        if bundle.structured_evidence
        else []
    )
    if not lines and bundle.level1_snapshot is not None:
        lines = _collect_level1_lines_from_snapshot(
            bundle.level1_snapshot,
            include_alias_mappings=include_alias_mappings,
        )

    if not lines:
        return None

    return (
        "<Narrative_Evidence_Level1>\n"
        "以下是当前片段相关的稳定实体事实；优先使用这些结构化事实，再结合局部上下文判断人物、实体类型与关系。\n"
        + "\n".join(lines)
        + "\n</Narrative_Evidence_Level1>"
    )


def render_annotation_evidence_blocks(bundle: EvidenceBundle) -> list[str]:
    """将 EvidenceBundle 渲染为 Phase 2 可消费的结构化证据块列表。"""

    blocks: list[str] = []

    structured_lines = [item.content for item in bundle.structured_evidence if item.content]
    if structured_lines:
        blocks.append("<Structured_Evidence>\n" + "\n".join(structured_lines) + "\n</Structured_Evidence>")

    disambig_candidates = render_disambig_candidates(bundle)
    if disambig_candidates:
        blocks.append(disambig_candidates)

    vector_evidence = render_vector_evidence(bundle)
    if vector_evidence:
        blocks.append(vector_evidence)

    return blocks


def render_annotation_prompt_blocks(
    bundle: EvidenceBundle,
    *,
    include_level1_alias_mappings: bool = True,
) -> AnnotationPromptBlocks:
    level1_facts = _render_annotation_level1(
        bundle,
        include_alias_mappings=include_level1_alias_mappings,
    )
    active_entities = _render_active_entity_lines(
        [item for item in bundle.local_evidence if item.evidence_type == "active_entity"]
    )
    disambig_context = render_disambig_candidates(bundle)
    vector_evidence = render_vector_evidence(bundle)
    prompt_sections = [section for section in (level1_facts, disambig_context, vector_evidence) if section]
    # 中文注释：annotation 主 prompt 当前只接收 active_entities + disambig_context 两个入口，
    # 因此这里显式把 Level 1 结构化事实并入 disambig_context，保证稳定事实真正进入主链路。
    combined_disambig = "\n\n".join(prompt_sections) if prompt_sections else None

    return AnnotationPromptBlocks(
        level1_facts=level1_facts,
        active_entities=active_entities,
        disambig_context=combined_disambig,
        vector_evidence=vector_evidence,
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

    blocks = (
        render_annotation_prompt_blocks(
            evidence_bundle,
            include_level1_alias_mappings=alias_map is None,
        )
        if evidence_bundle
        else None
    )

    sections: list[str] = []
    # 中文注释：active_entities 属于任务侧输入，不属于 EvidenceBundle 本体；
    # 如果上游已经给出带 fallback 的活跃实体上下文，就优先沿用，不再让 renderer 从 bundle 反推覆盖它。
    if active_entities is not None:
        sections.append(active_entities)
    elif blocks and blocks.active_entities:
        sections.append(blocks.active_entities)

    if blocks and blocks.disambig_context:
        sections.append(blocks.disambig_context)
    return sections
