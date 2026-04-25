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
    emotion_exemplars: str | None = None
    vector_evidence: str | None = None


@dataclass(slots=True)
class Level1EvidenceBuckets:
    alias_lines: list[str]
    entity_lines: list[str]
    relation_lines: list[str]


def _append_unique_line(bucket: list[str], seen_lines: set[str], line: str) -> None:
    if line not in seen_lines:
        bucket.append(line)
        seen_lines.add(line)


def _resolve_level1_relevant_names(
    snapshot: Level1AuthoritySnapshot,
    requested_names: Iterable[str] | None,
) -> set[str]:
    """
    创建时间: 2026-04-26
    任务: fix-empty-requested-names-level1-fallback
    说明: snapshot fallback 也必须遵守 request 边界；
          这里只保留当前 consumer 明确请求的名字，并在 alias 命中时补齐关联 canonical。
    """
    if requested_names is None:
        return set()

    normalized_requested_names = {
        str(name).strip() for name in requested_names if str(name).strip()
    }
    if not normalized_requested_names:
        return set()

    relevant_names = set(normalized_requested_names)
    related_canonicals = {
        mapping.canonical.strip()
        for mapping in snapshot.alias_mappings
        if mapping.alias.strip() in relevant_names and mapping.canonical.strip()
    }
    relevant_names |= related_canonicals
    return relevant_names


def _limit_items(items: list[Any], max_items: int | None) -> list[Any]:
    if max_items is None or max_items < 0:
        return items
    return items[:max_items]


def _trim_rendered_list_section(section: str | None, *, max_items: int | None) -> str | None:
    if not section:
        return None

    lines = section.splitlines()
    header_lines: list[str] = []
    item_lines: list[str] = []
    for line in lines:
        if line.startswith("- "):
            item_lines.append(line)
        else:
            header_lines.append(line)

    if not item_lines:
        return section

    limited_items = _limit_items(item_lines, max_items)
    if not limited_items:
        return None
    return "\n".join(header_lines + limited_items)


def _extract_disambig_source_name(line: str) -> str | None:
    if "「" not in line or "」" not in line:
        return None
    _, _, tail = line.partition("「")
    source_name, _, _ = tail.partition("」")
    source_name = source_name.strip()
    return source_name or None


def _prioritize_candidate_lines(
    candidate_lines: list[str],
    priority_names: Iterable[str] | None,
) -> list[str]:
    if not priority_names:
        return candidate_lines

    priority_name_set = {str(name).strip() for name in priority_names if str(name).strip()}
    if not priority_name_set:
        return candidate_lines

    prioritized: list[str] = []
    deferred: list[str] = []
    for line in candidate_lines:
        source_name = _extract_disambig_source_name(line)
        if source_name and source_name in priority_name_set:
            prioritized.append(line)
        else:
            deferred.append(line)
    return prioritized + deferred


def _collect_level1_lines_from_structured(
    bundle: EvidenceBundle,
    *,
    include_alias_mappings: bool = True,
) -> Level1EvidenceBuckets:
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

    return Level1EvidenceBuckets(
        alias_lines=alias_lines,
        entity_lines=entity_lines,
        relation_lines=relation_lines,
    )


def _collect_level1_lines_from_snapshot(
    snapshot: Level1AuthoritySnapshot,
    *,
    include_alias_mappings: bool = True,
    requested_names: Iterable[str] | None = None,
) -> Level1EvidenceBuckets:
    """
    创建时间: 2026-04-26
    任务: fix-empty-requested-names-level1-fallback
    说明: 当 renderer 只能从 snapshot 回退时，也要按 request 边界过滤；
          显式空请求或完全不命中时，不能重新渲染整本书的 Level1 事实。
    """
    alias_lines: list[str] = []
    entity_lines: list[str] = []
    relation_lines: list[str] = []
    seen_lines: set[str] = set()
    relevant_names = _resolve_level1_relevant_names(snapshot, requested_names)
    if requested_names is not None and not relevant_names:
        return Level1EvidenceBuckets(
            alias_lines=[],
            entity_lines=[],
            relation_lines=[],
        )

    entity_types = {
        item.name.strip(): item.entity_type.strip()
        for item in snapshot.entity_types
        if item.name
        and item.entity_type
        and (not relevant_names or item.name.strip() in relevant_names)
    }

    if include_alias_mappings:
        for mapping in snapshot.alias_mappings:
            alias = mapping.alias.strip()
            canonical = mapping.canonical.strip()
            if relevant_names and alias not in relevant_names and canonical not in relevant_names:
                continue
            if alias and canonical:
                _append_unique_line(alias_lines, seen_lines, f"- 已确认别名：{alias} -> {canonical}")

    for entity in snapshot.canonical_entities:
        name = entity.name.strip()
        if not name:
            continue
        if relevant_names and name not in relevant_names:
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
        if relevant_names and from_name not in relevant_names and to_name not in relevant_names:
            continue
        if from_name and to_name and relation_type:
            _append_unique_line(relation_lines, seen_lines, f"- 已确认关系：{from_name} -{relation_type}-> {to_name}")

    return Level1EvidenceBuckets(
        alias_lines=alias_lines,
        entity_lines=entity_lines,
        relation_lines=relation_lines,
    )


def render_level1_facts(
    bundle: EvidenceBundle,
    *,
    include_alias_mappings: bool = True,
    max_lines: int | None = None,
    max_alias_lines: int | None = None,
    max_entity_lines: int | None = None,
    max_relation_lines: int | None = None,
) -> str | None:
    """
    修改时间: 2026-04-26
    任务: fix-empty-requested-names-level1-fallback
    修改说明: renderer fallback 到 `level1_snapshot` 时也要按 `bundle.requested_names`
              过滤，显式空请求或快照 miss 都不允许回退成全量 Level1 注入。
    """
    buckets = (
        _collect_level1_lines_from_structured(bundle, include_alias_mappings=include_alias_mappings)
        if bundle.structured_evidence
        else Level1EvidenceBuckets(alias_lines=[], entity_lines=[], relation_lines=[])
    )
    if (
        not (buckets.alias_lines or buckets.entity_lines or buckets.relation_lines)
        and bundle.level1_snapshot is not None
    ):
        buckets = _collect_level1_lines_from_snapshot(
            bundle.level1_snapshot,
            include_alias_mappings=include_alias_mappings,
            requested_names=bundle.requested_names,
        )

    if any(limit is not None for limit in (max_alias_lines, max_entity_lines, max_relation_lines)):
        lines = (
            _limit_items(buckets.alias_lines, max_alias_lines)
            + _limit_items(buckets.entity_lines, max_entity_lines)
            + _limit_items(buckets.relation_lines, max_relation_lines)
        )
        if max_lines is not None:
            lines = _limit_items(lines, max_lines)
    else:
        lines = _limit_items(
            buckets.alias_lines + buckets.entity_lines + buckets.relation_lines,
            max_lines,
        )

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
    priority_names: Iterable[str] | None = None,
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

    candidate_lines = _prioritize_candidate_lines(candidate_lines, priority_names)
    candidate_lines = _limit_items(candidate_lines, max_candidates)
    if not candidate_lines:
        return None
    return "<Disambig_Candidates>\n" + "\n".join(candidate_lines) + "\n</Disambig_Candidates>"


def _select_semantic_items(
    bundle: EvidenceBundle,
    *,
    evidence_types: set[str],
    max_items: int | None,
) -> list[EvidenceItem]:
    """
    修改时间: 2026-04-21
    任务: emotion-rag-evidence-provider
    新建原因: semantic_evidence 现在承载多种用途，需要在 renderer 层按 evidence_type 分流，避免不同消费者互相污染。
    """
    filtered_items = [item for item in bundle.semantic_evidence if item.evidence_type in evidence_types]
    return filtered_items if max_items is None else filtered_items[:max_items]


def _collect_semantic_chunk_ids(
    bundle: EvidenceBundle,
    *,
    evidence_types: set[str],
) -> set[int]:
    """
    创建时间: 2026-04-21
    修改时间: 2026-04-21
    任务: dedupe-phase1-emotion-exemplar
    新建原因: Phase1 会同时消费 emotion exemplar 和 vector evidence，需要按
    chunk_id 去重，避免同一条 Level3 命中在 prompt 里重复出现。
    """
    chunk_ids: set[int] = set()
    for item in bundle.semantic_evidence:
        if item.evidence_type not in evidence_types or item.chunk_id is None:
            continue
        chunk_ids.add(item.chunk_id)
    return chunk_ids


def _prioritize_semantic_items(
    items: list[EvidenceItem],
    *,
    priority_names: Iterable[str] | None,
) -> list[EvidenceItem]:
    """
    创建时间: 2026-04-25
    任务: evidence-service-request-unification
    说明: `background_entities` 只作为 renderer 侧背景 hint 使用；
          这里仅调整 vector evidence 的展示顺序，不回流到 requested_names/candidate_names。
    """
    if not priority_names:
        return items

    priority_set = {str(name).strip() for name in priority_names if str(name).strip()}
    if not priority_set:
        return items

    prioritized: list[EvidenceItem] = []
    deferred: list[EvidenceItem] = []
    for item in items:
        text_candidates = (
            str(item.metadata.get("local_preview") or ""),
            str(item.metadata.get("text") or ""),
            str(item.content or ""),
        )
        item_text = "\n".join(part for part in text_candidates if part)
        if any(name in item_text for name in priority_set):
            prioritized.append(item)
        else:
            deferred.append(item)
    return prioritized + deferred


def render_vector_evidence(
    bundle: EvidenceBundle,
    max_chunks: int = 3,
    max_text_len: int = 200,
    exclude_chunk_ids: set[int] | None = None,
    priority_names: Iterable[str] | None = None,
) -> str | None:
    # 中文注释：这里仅渲染通用 semantic recall，避免把专门给情绪判断的 exemplar 混入旧的向量证据消费者。
    # 若 Phase1 已单独渲染 emotion exemplar，则再按 chunk_id 排除重复项，避免同一条历史片段占掉两类证据预算。
    # 修改时间: 2026-04-24
    # 任务: level3-paragraph-rerank
    # 修改说明: paragraph rerank 可提供 local_preview；渲染时优先展示局部 evidence，chunk 全文仍保留在 metadata 里兜底。
    selected_items = _select_semantic_items(
        bundle,
        evidence_types={"semantic_recall", "vector_evidence"},
        max_items=None,
    )
    if exclude_chunk_ids is not None:
        selected_items = [
            item
            for item in selected_items
            if item.chunk_id is None or item.chunk_id not in exclude_chunk_ids
        ]
    selected_items = _prioritize_semantic_items(
        selected_items,
        priority_names=priority_names,
    )

    vector_parts: list[str] = []
    for item in selected_items[:max_chunks]:
        if exclude_chunk_ids is not None and item.chunk_id is not None and item.chunk_id in exclude_chunk_ids:
            continue
        chunk_id = item.chunk_id if item.chunk_id is not None else item.metadata.get("chunk_id", "?")
        score = item.score if item.score is not None else item.metadata.get("similarity", 0.0)
        text = str(item.metadata.get("local_preview") or item.metadata.get("text", item.content))
        paragraph_index = item.metadata.get("paragraph_index")
        location_label = f"[Chunk {chunk_id}]"
        if paragraph_index is not None:
            location_label += f" [Paragraph {paragraph_index}]"
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        vector_parts.append(f"{location_label} (相似度: {float(score):.2f})\n{preview}")

    if not vector_parts:
        return None
    return (
        "<Vector_Evidence>\n"
        "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
        + "\n\n".join(vector_parts)
        + "\n</Vector_Evidence>"
    )


def render_emotion_exemplars(bundle: EvidenceBundle, max_chunks: int = 2, max_text_len: int = 160) -> str | None:
    """
    修改时间: 2026-04-21
    任务: emotion-rag-evidence-provider
    新建原因: 为 Phase1 提供相似情绪案例证据，但仍然复用统一的 semantic_evidence 主路径。
    """
    exemplar_parts: list[str] = []
    for item in _select_semantic_items(
        bundle,
        evidence_types={"emotion_exemplar"},
        max_items=max_chunks,
    ):
        chunk_id = item.chunk_id if item.chunk_id is not None else item.metadata.get("chunk_id", "?")
        score = item.score if item.score is not None else item.metadata.get("similarity", 0.0)
        text = str(item.metadata.get("text", item.content))
        emotional_valence = str(item.metadata.get("emotional_valence", "unknown"))
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        exemplar_parts.append(f"[Chunk {chunk_id}] (相似度: {float(score):.2f}, 情绪: {emotional_valence})\n{preview}")

    if not exemplar_parts:
        return None
    return (
        "<Emotion_Exemplars>\n"
        "以下是与当前片段情绪表达相近的历史片段，可作为整体情绪判断的辅助案例：\n"
        + "\n\n".join(exemplar_parts)
        + "\n</Emotion_Exemplars>"
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
    max_level1_alias_lines: int | None = None,
    max_level1_entity_lines: int | None = None,
    max_level1_relation_lines: int | None = None,
    max_active_entities: int | None = None,
    max_disambig_candidates: int | None = None,
    max_emotion_exemplars: int | None = None,
    max_emotion_text_len: int = 160,
    max_vector_chunks: int = 3,
    max_vector_text_len: int = 200,
    priority_candidate_names: Iterable[str] | None = None,
    exclude_vector_chunks_with_emotion_exemplars: bool = False,
) -> SharedEvidenceSections:
    if bundle is None:
        return SharedEvidenceSections()

    active_entity_items = [item for item in bundle.local_evidence if item.evidence_type == "active_entity"]
    background_entities = bundle.request_meta.get("background_entities")
    emotion_exemplar_chunk_ids = (
        _collect_semantic_chunk_ids(
            bundle,
            evidence_types={"emotion_exemplar"},
        )
        if exclude_vector_chunks_with_emotion_exemplars
        else set()
    )
    return SharedEvidenceSections(
        structured_evidence=render_structured_evidence(bundle),
        level1_facts=render_level1_facts(
            bundle,
            include_alias_mappings=include_level1_alias_mappings,
            max_lines=max_level1_lines,
            max_alias_lines=max_level1_alias_lines,
            max_entity_lines=max_level1_entity_lines,
            max_relation_lines=max_level1_relation_lines,
        ),
        active_entities=render_active_entities(
            active_entity_items,
            max_items=max_active_entities,
        ),
        disambig_candidates=render_disambig_candidates(
            bundle,
            fallback_requested_names=fallback_requested_names,
            max_candidates=max_disambig_candidates,
            priority_names=priority_candidate_names,
        ),
        emotion_exemplars=render_emotion_exemplars(
            bundle,
            max_chunks=max_emotion_exemplars if max_emotion_exemplars is not None else 2,
            max_text_len=max_emotion_text_len,
        ),
        vector_evidence=render_vector_evidence(
            bundle,
            max_chunks=max_vector_chunks,
            max_text_len=max_vector_text_len,
            exclude_chunk_ids=emotion_exemplar_chunk_ids if emotion_exemplar_chunk_ids else None,
            priority_names=background_entities,
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


def trim_active_entities_section(
    active_entities: str | None,
    *,
    max_items: int | None,
) -> str | None:
    return _trim_rendered_list_section(active_entities, max_items=max_items)
