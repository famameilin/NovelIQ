from __future__ import annotations

from dataclasses import dataclass

from src.rag.evidence_types import EvidenceBundle, EvidenceItem


@dataclass(slots=True)
class AnnotationPromptBlocks:
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
        last_action = str(item.metadata.get("last_action") or "")
        last_emotion = str(item.metadata.get("last_emotion") or "")
        chunk_id = item.metadata.get("chunk_id")

        detail_parts = [part for part in [last_action, last_emotion] if part]
        detail = "；".join(detail_parts) if detail_parts else "（无近期动作）"
        if chunk_id is not None:
            lines.append(f"- {name}（{role}）：{detail} [chunk={chunk_id}]")
        else:
            lines.append(f"- {name}（{role}）：{detail}")
    return "\n".join(lines)


def _render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    if not bundle.requested_names or not bundle.local_evidence:
        return None

    exact_aliases = {item.alias for item in bundle.level1_snapshot.alias_mappings} if bundle.level1_snapshot else set()
    active_names = [
        str(item.metadata.get("name", item.content))
        for item in bundle.local_evidence
        if item.evidence_type == "active_entity"
    ]
    candidate_names = [name for name in active_names if name]
    if not candidate_names:
        return None

    lines: list[str] = []
    for name in bundle.requested_names:
        if name in exact_aliases:
            continue
        candidates = [candidate for candidate in candidate_names if candidate != name][:5]
        if candidates:
            lines.append(f"- 「{name}」可能是：{'、'.join(candidates)}")

    if not lines:
        return None
    return "<Disambig_Candidates>\n" + "\n".join(lines) + "\n</Disambig_Candidates>"


def render_vector_evidence(bundle: EvidenceBundle, max_chunks: int = 3, max_text_len: int = 200) -> str | None:
    if not bundle.semantic_evidence:
        return None

    evidence_parts: list[str] = []
    for item in bundle.semantic_evidence[:max_chunks]:
        chunk_id = item.metadata.get("chunk_id", "?")
        similarity = float(item.metadata.get("similarity", 0.0))
        text = item.metadata.get("text", item.content)
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        evidence_parts.append(f"[Chunk {chunk_id}] (相似度: {similarity:.2f})\n{preview}")

    return (
        "<Vector_Evidence>\n"
        "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
        + "\n\n".join(evidence_parts)
        + "\n</Vector_Evidence>"
    )


def render_annotation_prompt_blocks(bundle: EvidenceBundle) -> AnnotationPromptBlocks:
    active_entities = _render_active_entity_lines(
        [item for item in bundle.local_evidence if item.evidence_type == "active_entity"]
    )
    disambig_context = _render_disambig_candidates(bundle)
    vector_evidence = render_vector_evidence(bundle)

    if disambig_context and vector_evidence:
        combined_disambig = disambig_context + "\n\n" + vector_evidence
    else:
        combined_disambig = disambig_context or vector_evidence

    return AnnotationPromptBlocks(
        active_entities=active_entities,
        disambig_context=combined_disambig,
        vector_evidence=vector_evidence,
    )

