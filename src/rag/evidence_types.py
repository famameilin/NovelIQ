from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AliasMapping:
    alias: str
    canonical: str
    source: str = "graph_alias_map"
    confidence: float | None = None


@dataclass(slots=True)
class CanonicalEntity:
    name: str
    entity_type: str = "character"
    source: str = "graph_entities"


@dataclass(slots=True)
class ConfirmedRelation:
    from_name: str
    to_name: str
    relation_type: str
    is_active: bool = True
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    support_count: int | None = None
    latest_event_id: int | None = None
    source: str = "graph_relations_current"


@dataclass(slots=True)
class EntityTypeFact:
    name: str
    entity_type: str
    source: str = "graph_entities"


@dataclass(slots=True)
class Level1AuthoritySnapshot:
    alias_mappings: list[AliasMapping] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


@dataclass(slots=True)
class EvidenceItem:
    evidence_type: str
    source: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    score: float | None = None
    chunk_id: int | None = None

    def __post_init__(self) -> None:
        if self.confidence is None:
            raw_confidence = self.metadata.get("confidence")
            self.confidence = float(raw_confidence) if raw_confidence is not None else None
        else:
            self.metadata.setdefault("confidence", self.confidence)

        if self.score is None:
            raw_score = self.metadata.get("score", self.metadata.get("similarity"))
            self.score = float(raw_score) if raw_score is not None else None
        else:
            self.metadata.setdefault("score", self.score)
            self.metadata.setdefault("similarity", self.score)

        if self.chunk_id is None:
            raw_chunk_id = self.metadata.get("chunk_id")
            self.chunk_id = int(raw_chunk_id) if raw_chunk_id is not None else None
        else:
            self.metadata.setdefault("chunk_id", self.chunk_id)


@dataclass(slots=True)
class EvidenceBundle:
    structured_evidence: list[EvidenceItem] = field(default_factory=list)
    local_evidence: list[EvidenceItem] = field(default_factory=list)
    semantic_evidence: list[EvidenceItem] = field(default_factory=list)
    requested_names: list[str] = field(default_factory=list)
    level1_snapshot: Level1AuthoritySnapshot | None = None

    def structured_alias_map(self) -> dict[str, str]:
        alias_map: dict[str, str] = {}

        for item in self.structured_evidence:
            if item.evidence_type != "alias_mapping":
                continue
            alias = str(item.metadata.get("alias", "")).strip()
            canonical = str(item.metadata.get("canonical", "")).strip()
            if not alias or not canonical:
                parts = item.content.replace("->", "→").split("→", maxsplit=1)
                if len(parts) == 2:
                    alias = alias or parts[0].strip()
                    canonical = canonical or parts[1].strip()
            if alias and canonical:
                alias_map[alias] = canonical

        if alias_map:
            return alias_map

        if self.level1_snapshot is None:
            return {}

        return {
            mapping.alias: mapping.canonical
            for mapping in self.level1_snapshot.alias_mappings
            if mapping.alias and mapping.canonical and mapping.alias != mapping.canonical
        }

    def to_prompt_blocks(self) -> dict[str, str]:
        structured_lines = [item.content for item in self.structured_evidence if item.content]
        structured_evidence = (
            "<Structured_Evidence>\n" + "\n".join(structured_lines) + "\n</Structured_Evidence>"
            if structured_lines
            else ""
        )

        candidate_lines = [item.content for item in self.local_evidence if item.evidence_type == "disambig_candidate"]
        if not candidate_lines and self.requested_names:
            exact_aliases = set(self.structured_alias_map().keys())
            active_names = [
                str(item.metadata.get("name", item.content)).strip()
                for item in self.local_evidence
                if item.evidence_type == "active_entity"
            ]
            for name in self.requested_names:
                if name in exact_aliases:
                    continue
                candidates = [candidate for candidate in active_names if candidate and candidate != name][:5]
                if candidates:
                    candidate_lines.append(f"「{name}」可能是：{'、'.join(candidates)}")

        disambig_candidates = (
            "<Disambig_Candidates>\n" + "\n".join(candidate_lines) + "\n</Disambig_Candidates>"
            if candidate_lines
            else ""
        )

        vector_parts: list[str] = []
        for item in self.semantic_evidence[:3]:
            chunk_id = item.chunk_id if item.chunk_id is not None else item.metadata.get("chunk_id", "?")
            score = item.score if item.score is not None else item.metadata.get("similarity", 0.0)
            text = str(item.metadata.get("text", item.content))
            preview = text[:200] + "..." if len(text) > 200 else text
            vector_parts.append(f"[Chunk {chunk_id}] (相似度: {float(score):.2f})\n{preview}")

        vector_evidence = (
            "<Vector_Evidence>\n"
            "以下是与当前上下文语义相似的历史片段，可能存在身份关联：\n"
            + "\n\n".join(vector_parts)
            + "\n</Vector_Evidence>"
            if vector_parts
            else ""
        )

        return {
            "structured_evidence": structured_evidence,
            "disambig_candidates": disambig_candidates,
            "vector_evidence": vector_evidence,
        }
