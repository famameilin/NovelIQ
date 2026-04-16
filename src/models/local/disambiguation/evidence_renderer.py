from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


def _read_legacy_or_shared_block(
    bundle: EvidenceBundle,
    render_attr: str,
    block_key: str,
) -> str | None:
    shared_renderer = getattr(bundle, render_attr, None)
    if callable(shared_renderer):
        rendered = shared_renderer()
        if isinstance(rendered, str) and rendered:
            return rendered

    legacy_builder = getattr(bundle, "to_prompt_blocks", None)
    if not callable(legacy_builder):
        return None

    blocks = legacy_builder()
    if isinstance(blocks, dict):
        value = blocks.get(block_key)
        return value if isinstance(value, str) and value else None
    return None


def render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    return _read_legacy_or_shared_block(bundle, "render_disambig_candidates", "disambig_candidates")


def render_disambig_prompt_context(bundle: EvidenceBundle) -> str | None:
    disambig_candidates = _read_legacy_or_shared_block(bundle, "render_disambig_candidates", "disambig_candidates")
    vector_evidence = _read_legacy_or_shared_block(bundle, "render_vector_evidence", "vector_evidence")

    if disambig_candidates and vector_evidence:
        return disambig_candidates + "\n\n" + vector_evidence
    return disambig_candidates or vector_evidence or None


def render_graph_feedback_hint(
    bundle: EvidenceBundle,
    existing_names: list[str],
    base_hint: str | None = None,
) -> str | None:
    parts: list[str] = []
    if base_hint:
        parts.append(base_hint)

    snapshot = bundle.level1_snapshot
    if snapshot is None:
        return base_hint

    existing_set = set(existing_names)

    alias_lines = [
        f"- {mapping.alias} → {mapping.canonical}"
        for mapping in snapshot.alias_mappings
        if mapping.alias != mapping.canonical and mapping.canonical in existing_set
    ]
    if alias_lines:
        parts.append("【图谱已裁决的别名映射】\n" + "\n".join(alias_lines))

    relation_lines = [
        f"- {relation.from_name} ←{relation.relation_type}→ {relation.to_name}"
        for relation in snapshot.confirmed_relations
        if relation.is_active and (relation.from_name in existing_set or relation.to_name in existing_set)
    ]
    if relation_lines:
        parts.append("【图谱已确认的关系】\n" + "\n".join(relation_lines[:10]))

    if not parts:
        return base_hint
    return "\n".join(parts)
