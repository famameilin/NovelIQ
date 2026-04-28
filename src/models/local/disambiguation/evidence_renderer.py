from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.models.local.evidence_renderer_shared import (
    render_shared_evidence_sections,
    select_shared_evidence_sections,
)

from .evidence import build_evidence_profile, format_evidence_profile

if TYPE_CHECKING:
    from src.rag.evidence_types import EvidenceBundle


@dataclass(slots=True)
class DisambiguationPromptContext:
    existing_character_hint: str | None = None
    graph_hint: str | None = None
    shared_evidence_context: str | None = None


@dataclass(frozen=True, slots=True)
class DisambiguationPromptPolicy:
    max_existing_anchor_entities: int = 6
    max_graph_hint_lines: int = 6
    max_disambig_candidates: int = 3
    max_vector_chunks: int = 2
    max_vector_text_len: int = 140


_DISAMBIG_PROMPT_POLICY = DisambiguationPromptPolicy()


def build_disambiguation_prompt_context(
    *,
    existing_character_hint: str | None = None,
    graph_hint: str | None = None,
    shared_evidence_context: str | None = None,
) -> DisambiguationPromptContext | None:
    """构建消歧任务上下文对象。"""

    if not any((existing_character_hint, graph_hint, shared_evidence_context)):
        return None
    return DisambiguationPromptContext(
        existing_character_hint=existing_character_hint,
        graph_hint=graph_hint,
        shared_evidence_context=shared_evidence_context,
    )


def _split_bulleted_section_groups(section: str | None) -> tuple[list[str], list[list[str]]]:
    if not section:
        return [], []

    header_lines: list[str] = []
    groups: list[list[str]] = []
    current_group: list[str] | None = None

    for line in section.splitlines():
        if line.startswith("- "):
            if current_group:
                groups.append(current_group)
            current_group = [line]
            continue
        if current_group is None:
            header_lines.append(line)
            continue
        current_group.append(line)

    if current_group:
        groups.append(current_group)

    return header_lines, groups


def _split_bulleted_sections(section: str | None) -> list[tuple[list[str], list[list[str]]]]:
    if not section:
        return []

    sections: list[tuple[list[str], list[list[str]]]] = []
    header_lines: list[str] = []
    groups: list[list[str]] = []
    current_group: list[str] | None = None

    for line in section.splitlines():
        if line.startswith("【") and not line.startswith("- "):
            if current_group:
                groups.append(current_group)
                current_group = None
            if header_lines or groups:
                sections.append((header_lines, groups))
            header_lines = [line]
            groups = []
            continue
        if line.startswith("- "):
            if current_group:
                groups.append(current_group)
            current_group = [line]
            continue
        if current_group is None:
            header_lines.append(line)
            continue
        current_group.append(line)

    if current_group:
        groups.append(current_group)
    if header_lines or groups:
        sections.append((header_lines, groups))

    return sections


def _prioritize_section_groups(
    groups: list[list[str]],
    *,
    priority_names: Iterable[str] | None,
) -> list[list[str]]:
    if not priority_names:
        return groups

    priority_set = {str(name).strip() for name in priority_names if str(name).strip()}
    if not priority_set:
        return groups

    prioritized: list[list[str]] = []
    deferred: list[list[str]] = []
    for group in groups:
        group_text = "\n".join(group)
        if any(name in group_text for name in priority_set):
            prioritized.append(group)
        else:
            deferred.append(group)
    return prioritized + deferred


def _limit_bulleted_section_groups(
    section: str | None,
    *,
    max_groups: int | None,
    priority_names: Iterable[str] | None = None,
) -> str | None:
    if not section:
        return None

    sections = _split_bulleted_sections(section)
    if not sections:
        header_lines, groups = _split_bulleted_section_groups(section)
        if not groups:
            return section
        groups = _prioritize_section_groups(groups, priority_names=priority_names)
        if max_groups is not None and max_groups >= 0:
            groups = groups[:max_groups]
        if not groups:
            return None
        rendered_groups = ["\n".join(group) for group in groups]
        return "\n".join(header_lines + rendered_groups)

    remaining = max_groups
    rendered_sections: list[str] = []
    for header_lines, groups in sections:
        if not groups:
            continue
        groups = _prioritize_section_groups(groups, priority_names=priority_names)
        if remaining is not None:
            if remaining <= 0:
                break
            groups = groups[:remaining]
        if not groups:
            continue
        rendered_sections.append("\n".join(header_lines + ["\n".join(group) for group in groups]))
        if remaining is not None:
            remaining -= len(groups)

    if not rendered_sections:
        return section
    return "\n".join(rendered_sections)


def render_existing_character_hint(
    existing_names: list[str] | None,
    existing_context_sentences: dict[str, str] | None = None,
    *,
    candidate_names: Iterable[str] | None = None,
    max_entities: int | None = None,
) -> str | None:
    """构建与当前 candidate 集强相关的已有角色锚点。"""

    if not existing_names:
        return None

    candidate_set = {str(name).strip() for name in candidate_names or [] if str(name).strip()}
    related_names: list[str] = []

    for name in existing_names:
        context = (existing_context_sentences or {}).get(name, "").strip()
        if candidate_set and (name in candidate_set or any(candidate in context for candidate in candidate_set)):
            related_names.append(name)

    selected_names = related_names or existing_names
    max_entities = _DISAMBIG_PROMPT_POLICY.max_existing_anchor_entities if max_entities is None else max_entities
    if max_entities >= 0:
        selected_names = selected_names[:max_entities]
    if not selected_names:
        return None

    lines = ["【已存在角色锚点】"]
    for name in selected_names:
        context = (existing_context_sentences or {}).get(name, "").strip()
        evidence_profile = build_evidence_profile(context)
        lines.append(f"- {name}")
        lines.append(f"  {format_evidence_profile(evidence_profile)}")
        if context:
            lines.append(f"  参考上下文：{context}")

    return "\n".join(lines)


def render_disambiguation_prompt_context_sections(
    prompt_context: DisambiguationPromptContext | None,
) -> list[str]:
    """按固定顺序渲染消歧任务上下文。
    这里的顺序就是消歧公共接口的正式消费顺序，
    先放已有角色锚点，再放图谱提示，最后放共享 evidence block。
    """

    if prompt_context is None:
        return []
    return [
        section
        for section in (
            prompt_context.existing_character_hint,
            prompt_context.graph_hint,
            prompt_context.shared_evidence_context,
        )
        if section
    ]


def render_disambig_candidates(
    bundle: EvidenceBundle,
    *,
    fallback_requested_names: Iterable[str] | None = None,
) -> str | None:
    return render_shared_evidence_sections(
        bundle,
        fallback_requested_names=fallback_requested_names,
    ).disambig_candidates


def render_disambig_prompt_context(
    bundle: EvidenceBundle,
    *,
    fallback_requested_names: Iterable[str] | None = None,
    priority_names: Iterable[str] | None = None,
) -> str | None:
    # 消歧 prompt 只消费共享 renderer 产出的 block，不再回读 bundle 上的渲染方法。
    shared_sections = render_shared_evidence_sections(
        bundle,
        fallback_requested_names=fallback_requested_names,
        max_disambig_candidates=_DISAMBIG_PROMPT_POLICY.max_disambig_candidates,
        max_vector_chunks=_DISAMBIG_PROMPT_POLICY.max_vector_chunks,
        max_vector_text_len=_DISAMBIG_PROMPT_POLICY.max_vector_text_len,
        priority_candidate_names=priority_names,
    )
    ordered_sections = select_shared_evidence_sections(
        shared_sections,
        ("disambig_candidates", "vector_evidence"),
    )
    return "\n\n".join(ordered_sections) if ordered_sections else None


def render_disambiguation_graph_hint(
    alias_map: dict[str, str],
    relations: Sequence[object],
    existing_names: list[str],
    *,
    candidate_names: Iterable[str] | None = None,
    max_lines: int | None = None,
) -> str | None:
    """将图谱权威数据渲染为消歧专用提示。
    说明: 将 build_graph_feedback_hint 逻辑从 DisambigContextProvider 迁移至 renderer 层，
          符合 evidence layer 的 provider/renderer 职责分离原则。
    """

    def _relation_field(relation: object, field_name: str) -> object:
        """
        读取关系提示字段。

        说明: 正式路径读取 CurrentRelationRow DTO；保留 dict 读取仅用于旧测试 stub。
        """
        if isinstance(relation, dict):
            legacy_name = "type" if field_name == "relation_type" else field_name
            return relation.get(legacy_name)
        return getattr(relation, field_name, None)

    existing_set = set(existing_names)
    candidate_set = {str(name).strip() for name in candidate_names or [] if str(name).strip()}
    related_name_set = set(candidate_set)
    for name in candidate_set:
        canonical = alias_map.get(name)
        if canonical:
            related_name_set.add(canonical)

    parts: list[str] = []

    graph_aliases = {
        a: c
        for a, c in alias_map.items()
        if a != c and c in existing_set and (not related_name_set or a in related_name_set or c in related_name_set)
    }
    if graph_aliases:
        alias_lines = ["【图谱已裁决的别名映射】"]
        for alias, canonical in sorted(graph_aliases.items()):
            alias_lines.append(f"- {alias} → {canonical}")
        parts.append("\n".join(alias_lines))

    relevant_rels = [
        r
        for r in relations
        if _relation_field(r, "is_active") is not False
        and (_relation_field(r, "from_name") in existing_set or _relation_field(r, "to_name") in existing_set)
        and (
            not related_name_set
            or _relation_field(r, "from_name") in related_name_set
            or _relation_field(r, "to_name") in related_name_set
        )
    ]
    if relevant_rels:
        rel_lines = ["【图谱已确认的关系】"]
        for relation in relevant_rels:
            rel_lines.append(
                f"- {_relation_field(relation, 'from_name')} "
                f"←{_relation_field(relation, 'relation_type')}→ "
                f"{_relation_field(relation, 'to_name')}"
            )
        parts.append("\n".join(rel_lines))

    if not parts:
        return None

    rendered = "\n".join(parts)
    return _limit_bulleted_section_groups(
        rendered,
        max_groups=max_lines if max_lines is not None else _DISAMBIG_PROMPT_POLICY.max_graph_hint_lines,
        priority_names=related_name_set or None,
    )
