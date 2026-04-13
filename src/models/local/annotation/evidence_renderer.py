from __future__ import annotations

from dataclasses import dataclass

from src.rag.evidence_types import EvidenceBundle, EvidenceItem, Level1AuthoritySnapshot


@dataclass(slots=True)
class AnnotationPromptBlocks:
    level1_facts: str | None = None
    active_entities: str | None = None
    disambig_context: str | None = None
    vector_evidence: str | None = None


@dataclass(slots=True)
class ForeshadowingPromptBlocks:
    level1_facts: str | None = None
    level2_context: str | None = None
    level3_echoes: str | None = None

    def sections(self) -> list[str]:
        return [section for section in (self.level1_facts, self.level2_context, self.level3_echoes) if section]


def _render_active_entity_lines(items: list[EvidenceItem]) -> str | None:
    if not items:
        return None

    lines = ["【近期活跃角色】"]
    for item in items:
        name = str(item.metadata.get("name", item.content))
        role = str(item.metadata.get("role") or "other")
        last_action = str(item.metadata.get("recent_action") or item.metadata.get("last_action") or "")
        last_emotion = str(item.metadata.get("recent_emotion") or item.metadata.get("last_emotion") or "")
        chunk_id = item.metadata.get("last_seen_chunk", item.metadata.get("chunk_id"))

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
        chunk_id = item.metadata.get("chunk_id", item.chunk_id if item.chunk_id is not None else "?")
        similarity = float(item.metadata.get("similarity", item.score if item.score is not None else 0.0))
        text = str(item.metadata.get("text", item.content))
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        evidence_parts.append(f"[Chunk {chunk_id}] (相似度: {similarity:.2f})\n{preview}")

    return (
        "<Vector_Evidence>\n"
        "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
        + "\n\n".join(evidence_parts)
        + "\n</Vector_Evidence>"
    )


def _append_unique_line(bucket: list[str], seen_lines: set[str], line: str) -> None:
    if line not in seen_lines:
        bucket.append(line)
        seen_lines.add(line)


def _collect_level1_lines_from_structured(bundle: EvidenceBundle) -> list[str]:
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


def _collect_level1_lines_from_snapshot(snapshot: Level1AuthoritySnapshot) -> list[str]:
    alias_lines: list[str] = []
    entity_lines: list[str] = []
    relation_lines: list[str] = []
    seen_lines: set[str] = set()
    entity_types = {
        item.name.strip(): item.entity_type.strip()
        for item in snapshot.entity_types
        if item.name and item.entity_type
    }

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


def _render_foreshadowing_level1(bundle: EvidenceBundle) -> str | None:
    lines = _collect_level1_lines_from_structured(bundle) if bundle.structured_evidence else []
    if not lines and bundle.level1_snapshot is not None:
        lines = _collect_level1_lines_from_snapshot(bundle.level1_snapshot)

    if not lines:
        return None

    return (
        "<Narrative_Evidence_Level1>\n"
        "以下是与当前片段相关的稳定实体事实，可用于判断是否存在提前埋线：\n"
        + "\n".join(lines)
        + "\n</Narrative_Evidence_Level1>"
    )


def _render_annotation_level1(bundle: EvidenceBundle) -> str | None:
    lines = _collect_level1_lines_from_structured(bundle) if bundle.structured_evidence else []
    if not lines and bundle.level1_snapshot is not None:
        lines = _collect_level1_lines_from_snapshot(bundle.level1_snapshot)

    if not lines:
        return None

    return (
        "<Narrative_Evidence_Level1>\n"
        "以下是当前片段相关的稳定实体事实；优先使用这些结构化事实，再结合局部上下文判断人物、实体类型与关系。\n"
        + "\n".join(lines)
        + "\n</Narrative_Evidence_Level1>"
    )


def _render_foreshadowing_level2(bundle: EvidenceBundle) -> str | None:
    active_lines = _render_active_entity_lines(
        [item for item in bundle.local_evidence if item.evidence_type == "active_entity"]
    )
    if not active_lines:
        return None

    payload = active_lines.replace("【近期活跃角色】\n", "", 1)
    return (
        "<Narrative_Evidence_Level2>\n"
        "以下是当前片段附近的近期活跃实体与状态，可辅助判断这段信息是否在为后文铺垫：\n"
        + payload
        + "\n</Narrative_Evidence_Level2>"
    )


def _render_foreshadowing_level3(bundle: EvidenceBundle, max_chunks: int = 3, max_text_len: int = 180) -> str | None:
    if not bundle.semantic_evidence:
        return None

    lines: list[str] = []
    for item in bundle.semantic_evidence[:max_chunks]:
        chunk_id = item.metadata.get("chunk_id", item.chunk_id if item.chunk_id is not None else "?")
        similarity = float(item.metadata.get("similarity", item.metadata.get("score", item.score or 0.0)))
        text = str(item.metadata.get("text", item.content))
        preview = text[:max_text_len] + "..." if len(text) > max_text_len else text
        lines.append(f"- [Chunk {chunk_id} | 相似度 {similarity:.2f}] {preview}")

    return (
        "<Narrative_Evidence_Level3>\n"
        "以下是语义相近的历史片段，只能作为弱证据，用于观察重复意象、线索回响或叙事呼应：\n"
        + "\n".join(lines)
        + "\n注意：这些历史片段不能直接作为 anchor_text；anchor_text 必须来自<当前文本>。\n"
        "</Narrative_Evidence_Level3>"
    )


def render_foreshadowing_prompt_blocks(bundle: EvidenceBundle) -> ForeshadowingPromptBlocks:
    return ForeshadowingPromptBlocks(
        level1_facts=_render_foreshadowing_level1(bundle),
        level2_context=_render_foreshadowing_level2(bundle),
        level3_echoes=_render_foreshadowing_level3(bundle),
    )


def render_annotation_evidence_blocks(bundle: EvidenceBundle) -> list[str]:
    """兼容旧测试和调用方，保持证据块输出顺序稳定。"""

    blocks = bundle.to_prompt_blocks()
    return [
        block
        for block in (
            blocks["structured_evidence"],
            blocks["disambig_candidates"],
            blocks["vector_evidence"],
        )
        if block
    ]


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
        level1_facts=_render_annotation_level1(bundle),
        active_entities=active_entities,
        disambig_context=combined_disambig,
        vector_evidence=vector_evidence,
    )
