from __future__ import annotations

from src.rag.evidence_types import EvidenceBundle


def render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    blocks = bundle.to_prompt_blocks()
    disambig_candidates = blocks["disambig_candidates"]
    return disambig_candidates or None


def render_disambig_prompt_context(bundle: EvidenceBundle) -> str | None:
    blocks = bundle.to_prompt_blocks()
    disambig_candidates = blocks["disambig_candidates"]
    vector_evidence = blocks["vector_evidence"]

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
