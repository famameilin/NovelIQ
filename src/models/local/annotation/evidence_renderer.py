"""
Phase1 annotation evidence renderer.

说明:
- Phase1 主链路直接消费 EvidenceBundle
- 旧的 XML-ish block 形状只在 renderer 内部维护，避免 workflow/context 再反向拼接字符串
"""

from __future__ import annotations

from src.rag import EvidenceBundle, EvidenceItem


def _render_structured_evidence(items: list[EvidenceItem]) -> str:
    alias_items = [item for item in items if item.evidence_type == "alias_mapping"]
    if not alias_items:
        return ""

    lines = ["<Structured_Evidence>"]
    for item in alias_items:
        lines.append(f"- {item.content}")
    lines.append("</Structured_Evidence>")
    return "\n".join(lines)


def _render_local_evidence(items: list[EvidenceItem]) -> str:
    disambig_items = [item for item in items if item.evidence_type == "disambig_candidate"]
    if not disambig_items:
        return ""

    lines = ["<Disambig_Candidates>"]
    for item in disambig_items:
        lines.append(f"- {item.content}")
    lines.append("</Disambig_Candidates>")
    return "\n".join(lines)


def _render_semantic_evidence(
    items: list[EvidenceItem],
    *,
    max_items: int = 3,
    max_chars: int = 200,
) -> str:
    vector_items = [item for item in items if item.evidence_type == "vector_evidence"]
    if not vector_items:
        return ""

    lines = ["<Vector_Evidence>"]
    lines.append("以下是与当前上下文语义相似的历史片段，可能存在身份关联：")
    for item in vector_items[:max_items]:
        chunk_id = item.chunk_id if item.chunk_id is not None else "?"
        similarity = item.score if item.score is not None else 0.0
        text_preview = item.content[:max_chars]
        if len(item.content) > max_chars:
            text_preview += "..."
        lines.append(f"[Chunk {chunk_id}] (相似度: {similarity:.2f})")
        lines.append(text_preview)
    lines.append("</Vector_Evidence>")
    return "\n".join(lines)


def render_annotation_evidence_blocks(
    evidence_bundle: EvidenceBundle,
    *,
    max_semantic_items: int = 3,
    max_semantic_chars: int = 200,
) -> list[str]:
    """Render prompt blocks for Phase1 annotation from structured evidence."""
    blocks = [
        _render_structured_evidence(evidence_bundle.structured_evidence),
        _render_local_evidence(evidence_bundle.local_evidence),
        _render_semantic_evidence(
            evidence_bundle.semantic_evidence,
            max_items=max_semantic_items,
            max_chars=max_semantic_chars,
        ),
    ]
    return [block for block in blocks if block]
