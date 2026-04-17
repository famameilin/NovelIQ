from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.local.evidence_renderer_shared import render_disambig_candidates as render_shared_disambig_candidates
from src.models.local.evidence_renderer_shared import render_vector_evidence

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


def render_disambig_candidates(bundle: EvidenceBundle) -> str | None:
    return render_shared_disambig_candidates(bundle)


def render_disambig_prompt_context(bundle: EvidenceBundle) -> str | None:
    # 中文注释：消歧 prompt 只消费共享 renderer 产出的 block，不再回读 bundle 上的渲染方法。
    disambig_candidates = render_shared_disambig_candidates(bundle)
    vector_evidence = render_vector_evidence(bundle)

    if disambig_candidates and vector_evidence:
        return disambig_candidates + "\n\n" + vector_evidence
    return disambig_candidates or vector_evidence or None


def render_disambiguation_graph_hint(
    alias_map: dict[str, str],
    relations: list[dict],
    existing_names: list[str],
) -> str | None:
    """将图谱权威数据渲染为消歧专用提示。

    创建时间: 2026-04-17
    创建者: TraeAI
    任务: refactor/split-provider-bundle-renderer
    说明: 将 build_graph_feedback_hint 逻辑从 DisambigContextProvider 迁移至 renderer 层，
          符合 evidence layer 的 provider/renderer 职责分离原则。
    """
    existing_set = set(existing_names)
    parts: list[str] = []

    graph_aliases = {a: c for a, c in alias_map.items() if a != c and c in existing_set}
    if graph_aliases:
        alias_lines = ["【图谱已裁决的别名映射】"]
        for alias, canonical in sorted(graph_aliases.items()):
            alias_lines.append(f"- {alias} → {canonical}")
        parts.append("\n".join(alias_lines))

    relevant_rels = [r for r in relations if r.get("from_name") in existing_set or r.get("to_name") in existing_set]
    if relevant_rels:
        rel_lines = ["【图谱已确认的关系】"]
        for relation in relevant_rels[:10]:
            rel_lines.append(f"- {relation.get('from_name')} ←{relation.get('type')}→ {relation.get('to_name')}")
        parts.append("\n".join(rel_lines))

    if not parts:
        return None

    return "\n".join(parts)
