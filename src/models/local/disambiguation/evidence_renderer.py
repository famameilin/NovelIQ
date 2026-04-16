from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


def _read_legacy_or_shared_block(
    bundle: EvidenceBundle,
    render_attr: str,
) -> str | None:
    shared_renderer = getattr(bundle, render_attr, None)
    if callable(shared_renderer):
        rendered = shared_renderer()
        if isinstance(rendered, str) and rendered:
            return rendered
    return None


def render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    return _read_legacy_or_shared_block(bundle, "render_disambig_candidates")


def render_disambig_prompt_context(bundle: EvidenceBundle) -> str | None:
    disambig_candidates = _read_legacy_or_shared_block(bundle, "render_disambig_candidates")
    vector_evidence = _read_legacy_or_shared_block(bundle, "render_vector_evidence")

    if disambig_candidates and vector_evidence:
        return disambig_candidates + "\n\n" + vector_evidence
    return disambig_candidates or vector_evidence or None
