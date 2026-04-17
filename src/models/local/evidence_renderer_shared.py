from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


def render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    # 中文注释：这里是共享 evidence 渲染层，只把 bundle 中已有的结构转成 prompt block，
    # 不承担 provider 侧的取证职责。
    candidate_lines = [item.content for item in bundle.local_evidence if item.evidence_type == "disambig_candidate"]
    if not candidate_lines and bundle.requested_names:
        exact_aliases = set(bundle.structured_alias_map().keys())
        active_names = [
            str(item.metadata.get("name", item.content)).strip()
            for item in bundle.local_evidence
            if item.evidence_type == "active_entity"
        ]
        for name in bundle.requested_names:
            if name in exact_aliases:
                continue
            candidates = [candidate for candidate in active_names if candidate and candidate != name][:5]
            if candidates:
                candidate_lines.append(f"「{name}」可能是：{'、'.join(candidates)}")

    if not candidate_lines:
        return None
    return "<Disambig_Candidates>\n" + "\n".join(candidate_lines) + "\n</Disambig_Candidates>"


def render_vector_evidence(bundle: EvidenceBundle, max_chunks: int = 3, max_text_len: int = 200) -> str | None:
    # 中文注释：Level 3 的展示文案统一留在 renderer 层，provider 只负责产出 semantic_evidence。
    vector_parts: list[str] = []
    for item in bundle.semantic_evidence[:max_chunks]:
        chunk_id = item.chunk_id if item.chunk_id is not None else item.metadata.get("chunk_id", "?")
        score = item.score if item.score is not None else item.metadata.get("similarity", 0.0)
        text = str(item.metadata.get("text", item.content))
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        vector_parts.append(f"[Chunk {chunk_id}] (相似度: {float(score):.2f})\n{preview}")

    if not vector_parts:
        return None
    return (
        "<Vector_Evidence>\n"
        "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
        + "\n\n".join(vector_parts)
        + "\n</Vector_Evidence>"
    )
