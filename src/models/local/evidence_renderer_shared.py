from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.knowledge.authority import ActiveEntityContext, Level1AuthoritySnapshot
    from src.rag.evidence_types import EvidenceBundle, EvidenceItem


@dataclass(slots=True)
class SharedEvidenceSections:
    structured_evidence: str | None = None
    level1_facts: str | None = None
    active_entities: str | None = None
    disambig_candidates: str | None = None
    vector_evidence: str | None = None


def _append_unique_line(bucket: list[str], seen_lines: set[str], line: str) -> None:
    if line not in seen_lines:
        bucket.append(line)
        seen_lines.add(line)


def _limit_items(items: list[Any], max_items: int | None) -> list[Any]:
    if max_items is None or max_items < 0:
        return items
    return items[:max_items]


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


def render_level1_facts(
    bundle: EvidenceBundle,
    *,
    include_alias_mappings: bool = True,
    max_lines: int | None = None,
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
    lines = _limit_items(lines, max_lines)

    if not lines:
        return None

    return (
        "<Narrative_Evidence_Level1>\n"
        "以下是当前片段相关的稳定实体事实；优先使用这些结构化事实，再结合局部上下文判断人物、实体类型与关系。\n"
        + "\n".join(lines)
        + "\n</Narrative_Evidence_Level1>"
    )


def _build_active_entity_records(
    items: Sequence[EvidenceItem],
) -> list[dict[str, Any]]:
    return [
        {
            "name": str(item.metadata.get("name", item.content)),
            "role": str(item.metadata.get("role") or "other"),
            "recent_action": str(item.metadata.get("recent_action") or item.metadata.get("last_action") or ""),
            "recent_emotion": str(item.metadata.get("recent_emotion") or item.metadata.get("last_emotion") or ""),
            "last_seen_chunk": item.metadata.get("last_seen_chunk", item.metadata.get("chunk_id")),
        }
        for item in items
    ]


def _render_active_entity_section(records: Iterable[dict[str, Any]]) -> str | None:
    rows = list(records)
    if not rows:
        return None

    lines = ["【近期活跃角色】"]
    for row in rows:
        name = str(row.get("name", "")).strip()
        if not name:
            continue
        role = str(row.get("role") or "other")
        last_action = str(row.get("recent_action") or row.get("last_action") or "")
        last_emotion = str(row.get("recent_emotion") or row.get("last_emotion") or "")
        chunk_id = row.get("last_seen_chunk", row.get("chunk_id"))

        detail_parts = [part for part in (last_action, last_emotion) if part]
        detail = "；".join(detail_parts) if detail_parts else "（无近期动作）"
        if chunk_id is not None:
            lines.append(f"- {name}（{role}）：{detail} [chunk={chunk_id}]")
        else:
            lines.append(f"- {name}（{role}）：{detail}")

    return "\n".join(lines) if len(lines) > 1 else None


def render_active_entities(
    items: Sequence[EvidenceItem],
    *,
    max_items: int | None = None,
) -> str | None:
    records = _build_active_entity_records(items)
    return _render_active_entity_section(_limit_items(records, max_items))


def render_active_entities_from_authority(active_entities: Iterable[ActiveEntityContext]) -> str | None:
    records = [
        {
            "name": item.name,
            "role": item.role,
            "recent_action": item.recent_action,
            "recent_emotion": item.recent_emotion,
            "last_seen_chunk": item.last_seen_chunk,
        }
        for item in active_entities
    ]
    return _render_active_entity_section(records)


def render_disambig_candidates(
    bundle: EvidenceBundle,
    *,
    fallback_requested_names: Iterable[str] | None = None,
    max_candidates: int | None = None,
) -> str | None:
    # 中文注释：这里是共享 evidence 渲染层，只把 bundle 中已有的结构转成 prompt block，
    # 不承担 provider 侧的取证职责。
    candidate_lines = [item.content for item in bundle.local_evidence if item.evidence_type == "disambig_candidate"]
    if not candidate_lines and bundle.requested_names:
        fallback_name_set = (
            {str(name).strip() for name in fallback_requested_names if str(name).strip()}
            if fallback_requested_names is not None
            else None
        )
        exact_aliases = set(bundle.structured_alias_map().keys())
        active_names = [
            str(item.metadata.get("name", item.content)).strip()
            for item in bundle.local_evidence
            if item.evidence_type == "active_entity"
        ]
        for name in bundle.requested_names:
            if fallback_name_set is not None and name not in fallback_name_set:
                continue
            if name in exact_aliases:
                continue
            candidates = [candidate for candidate in active_names if candidate and candidate != name][:5]
            if candidates:
                candidate_lines.append(f"「{name}」可能是：{'、'.join(candidates)}")

    candidate_lines = _limit_items(candidate_lines, max_candidates)
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


def render_structured_evidence(bundle: EvidenceBundle) -> str | None:
    structured_lines = [item.content for item in bundle.structured_evidence if item.content]
    if not structured_lines:
        return None
    return "<Structured_Evidence>\n" + "\n".join(structured_lines) + "\n</Structured_Evidence>"


def render_shared_evidence_sections(
    bundle: EvidenceBundle | None,
    *,
    include_level1_alias_mappings: bool = True,
    fallback_requested_names: Iterable[str] | None = None,
    max_level1_lines: int | None = None,
    max_active_entities: int | None = None,
    max_disambig_candidates: int | None = None,
    max_vector_chunks: int = 3,
    max_vector_text_len: int = 200,
) -> SharedEvidenceSections:
    if bundle is None:
        return SharedEvidenceSections()

    active_entity_items = [item for item in bundle.local_evidence if item.evidence_type == "active_entity"]
    return SharedEvidenceSections(
        structured_evidence=render_structured_evidence(bundle),
        level1_facts=render_level1_facts(
            bundle,
            include_alias_mappings=include_level1_alias_mappings,
            max_lines=max_level1_lines,
        ),
        active_entities=render_active_entities(
            active_entity_items,
            max_items=max_active_entities,
        ),
        disambig_candidates=render_disambig_candidates(
            bundle,
            fallback_requested_names=fallback_requested_names,
            max_candidates=max_disambig_candidates,
        ),
        vector_evidence=render_vector_evidence(
            bundle,
            max_chunks=max_vector_chunks,
            max_text_len=max_vector_text_len,
        ),
    )


def select_shared_evidence_sections(
    sections: SharedEvidenceSections,
    order: Sequence[str],
) -> list[str]:
    selected: list[str] = []
    for field_name in order:
        value = getattr(sections, field_name, None)
        if value:
            selected.append(value)
    return selected
