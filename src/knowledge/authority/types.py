from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# 中文注释：以下 allowlist 常量把 authority 输出矩阵直接固定在代码里。
# consumer 只能依赖自己那一层明确允许的字段，避免继续跨层借字段。
LEVEL1_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "alias_mappings": ("alias", "canonical", "confidence", "source"),
    "canonical_entities": (
        "name",
        "entity_type",
        "entity_id",
        "first_seen_chunk",
        "last_seen_chunk",
        "primary_role_function",
        "status",
        "source_confidence",
    ),
    "confirmed_relations": (
        "from_name",
        "to_name",
        "relation_type",
        "from_entity_id",
        "to_entity_id",
        "is_active",
        "first_seen_chunk",
        "last_seen_chunk",
        "change_count",
        "support_count",
        "latest_event_id",
        "tension_index",
    ),
    "entity_types": ("name", "entity_type"),
}


@dataclass(slots=True)
class AliasMapping:
    alias: str
    canonical: str
    source: str = "graph_alias_map"
    confidence: float | None = None


@dataclass(slots=True)
class CanonicalEntity:
    """
    Stable entity identity inside one run.

    Intentionally excludes transient prompt-local state like last_action or
    last_emotion_score so Level 1 stays a minimal reusable authority contract.
    """

    name: str
    entity_type: str = "character"
    entity_id: int | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    primary_role_function: str | None = None
    status: str = "active"
    source_confidence: float | None = None
    source: str = "graph_entities"


@dataclass(slots=True)
class ConfirmedRelation:
    """Current authority snapshot for a relation pair, without history."""

    from_name: str
    to_name: str
    relation_type: str
    from_entity_id: int | None = None
    to_entity_id: int | None = None
    is_active: bool = True
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    change_count: int | None = None
    support_count: int | None = None
    latest_event_id: int | None = None
    tension_index: float | None = None
    source: str = "graph_relations_current"


@dataclass(slots=True)
class RelationEvent:
    """Immutable relation history event for timeline/history consumers."""

    relation_event_id: int
    chunk_id: int
    from_entity_id: int
    to_entity_id: int
    from_name: str
    to_name: str
    relation_type: str
    change_type: str
    evidence: str | None = None
    confidence: float | None = None
    directionality: str | None = None
    source_relation_row_id: int | None = None
    source: str = "graph_relation_events"


@dataclass(slots=True)
class EntityTypeFact:
    name: str
    entity_type: str
    source: str = "graph_entities"


@dataclass(slots=True)
class EntityLifecycle:
    """
    Stable span/state metadata that can be safely reused across consumers.

    For timeline consumers this is the protected source of truth for
    character entry/exit spans. Downstream code should not re-derive
    lifecycle windows from repository rows.
    """

    entity_id: int
    name: str
    entity_type: str
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    status: str = "active"
    source: str = "graph_entities"


@dataclass(slots=True)
class ActiveEntityContext:
    """
    Level 2 local context contract for nearby active entities.

    This keeps prompt consumers off the repository row shape while still
    exposing the recent local state they need for annotation/disambiguation.
    """

    name: str
    entity_id: int | None = None
    role: str | None = None
    entity_type: str = "character"
    status: str = "active"
    last_seen_chunk: int | None = None
    recent_action: str | None = None
    recent_emotion: str | None = None
    source: str = "graph_active_entities"


@dataclass(slots=True)
class StableState:
    """
    Cross-chunk stable entity state.

    Intentionally excludes transient local context like last_action or local emotion.
    """

    entity_id: int
    name: str
    entity_type: str
    status: str = "active"
    primary_role_function: str | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    source_confidence: float | None = None
    source: str = "graph_entities"


@dataclass(slots=True)
class Level1AuthoritySnapshot:
    """
    Minimal Level 1 authority contract for evidence consumers.

    This snapshot exists to feed EvidenceBundle/Level1 assembly and should stay
    free of timeline history, graph product summaries, and prompt-local state.
    """

    alias_mappings: list[AliasMapping] = field(default_factory=list)
    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


# 中文注释：timeline 只允许消费角色子图、生命周期与关系事件三块共享字段，
# 不允许从 GraphAuthorityView 或 repository 原始形状反推历史语义。
TIMELINE_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "character_entities": ("entity_id", "name", "entity_type"),
    "entity_lifecycles": ("entity_id", "name", "entity_type", "first_seen_chunk", "last_seen_chunk"),
    "relation_events": (
        "chunk_id",
        "from_entity_id",
        "to_entity_id",
        "relation_type",
        "change_type",
        "evidence",
    ),
}


@dataclass(slots=True)
class TimelineAuthorityView:
    """
    Protected timeline-facing authority contract.

    The view is intentionally narrower than the full graph authority surface:
    - ``character_entities`` contains only the character subgraph.
    - ``entity_lifecycles`` stays aligned with that same character set.
    - ``relation_events`` contains immutable history events whose two endpoints
      both belong to the character subgraph.

    Timeline consumers should treat this as the shared contract and avoid
    depending on repository row shapes or current-relation projections.
    """

    character_entities: list[CanonicalEntity] = field(default_factory=list)
    entity_lifecycles: list[EntityLifecycle] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)


# 中文注释：graph page route assembler 只允许读取这三块 authority facts。
# 页面 summary / quality / events_page 仍由 route/product 层自己组装。
GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "stable_states": (
        "entity_id",
        "name",
        "entity_type",
        "status",
        "primary_role_function",
        "first_seen_chunk",
        "last_seen_chunk",
    ),
    "confirmed_relations": (
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "support_count",
        "change_count",
        "tension_index",
        "is_active",
    ),
    "relation_events": (
        "relation_event_id",
        "chunk_id",
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "change_type",
        "evidence",
        "confidence",
        "directionality",
        "source_relation_row_id",
    ),
}


@dataclass(slots=True)
class GraphAuthorityView:
    """
    Protected graph-facing authority facts.

    This contract deliberately stops at stable facts:
    - canonical entity identity
    - current confirmed relations
    - full immutable relation history events
    - stable entity states

    Product-layer summaries/quality cards belong to graph page assemblers,
    while diagnosis/aggregate conclusions belong to higher-level analysis.
    If another downstream needs a different slice, add a dedicated contract
    instead of borrowing repository rows or overloading Level1/Timeline
    boundaries.
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)
    stable_states: list[StableState] = field(default_factory=list)


@dataclass(slots=True)
class GraphSharedSummary:
    """
    Aggregate-only graph summary shared outside the graph product surface.

    Diagnosis/export may reuse these counters as graph-owned input signals,
    but richer highlights such as core characters and key relations must stay
    in graph-page-only contracts.
    """

    node_count: int = 0
    edge_count: int = 0
    density: float = 0.0

    def to_contract_dict(self) -> dict[str, float | int]:
        """Serialize the shared graph summary with an explicit field whitelist."""

        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "density": self.density,
        }


@dataclass(slots=True)
class GraphQualitySignals:
    """
    Aggregate-only graph quality counters shared outside the graph page.

    The detailed conflict / low-confidence samples belong to graph product
    presentation and should not flow into diagnosis/export/aggregate layers.
    """

    conflict_count: int = 0
    low_confidence_count: int = 0

    def to_contract_dict(self) -> dict[str, int]:
        """Serialize the shared graph quality counters with an explicit field whitelist."""

        return {
            "conflict_count": self.conflict_count,
            "low_confidence_count": self.low_confidence_count,
        }


# 中文注释：report 只给 diagnosis/export 共用聚合信号，字段必须保持最小集。
GRAPH_REPORT_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "summary": ("node_count", "edge_count", "density"),
    "quality": ("conflict_count", "low_confidence_count"),
}


@dataclass(slots=True)
class GraphKeyRelationHighlight:
    """Page-facing highlight for one representative confirmed relation."""

    from_name: str
    to_name: str
    relation_type: str | None = None
    support_count: int = 0


@dataclass(slots=True)
class GraphPageSummary:
    """
    Graph-page-only summary contract.

    中文说明：这里可以承载页面首屏高亮（如核心角色、关键关系），但这些字段
    不应进入 diagnosis/export/shared signals，否则 graph page 又会反向定义
    上层分析语义。
    """

    node_count: int = 0
    edge_count: int = 0
    density: float = 0.0
    core_characters: list[str] = field(default_factory=list)
    key_relations: list[GraphKeyRelationHighlight] = field(default_factory=list)


@dataclass(slots=True)
class GraphConflictSample:
    """Graph-page-only sample for relation type conflicts."""

    entity_pair: list[int | None] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    relation_count: int = 0
    latest_event_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class GraphLowConfidenceSample:
    """Graph-page-only sample for one low-confidence relation event."""

    relation_event_id: int
    chunk_id: int
    from_name: str
    to_name: str
    relation_type: str | None = None
    change_type: str | None = None
    confidence: float | None = None


@dataclass(slots=True)
class GraphPageQualityDetails:
    """
    Graph-page-only quality details.

    中文说明：共享层只拿 counters；样本明细只服务 graph page 的排障与解释，
    不允许 diagnosis/export 继续顺手复用这些字段。
    """

    conflict_count: int = 0
    low_confidence_count: int = 0
    conflicts: list[GraphConflictSample] = field(default_factory=list)
    low_confidence_samples: list[GraphLowConfidenceSample] = field(default_factory=list)


@dataclass(slots=True)
class ExportRelationSnapshot:
    """Current relation snapshot dedicated to legacy export payload assembly."""

    relation_id: int | None = None
    from_name: str = ""
    to_name: str = ""
    relation_type: str = ""
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    latest_event_id: int | None = None
    is_active: bool = True
    source: str = "graph_relations_current"


@dataclass(slots=True)
class ExportGraphAuthorityView:
    """
    Dedicated authority surface for legacy graph-derived export payloads.

    Results export still emits DTOs such as chunk-level relations and
    hierarchical relation summaries. This view keeps those payload builders off
    repository/projection row shapes without overloading GraphAuthorityView or
    GraphAuthorityReport with export-only concerns.
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    current_relations: list[ExportRelationSnapshot] = field(default_factory=list)
    relation_events: list[RelationEvent] = field(default_factory=list)


EXPORT_GRAPH_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "canonical_entities": (
        "name",
        "entity_type",
        "entity_id",
        "first_seen_chunk",
        "last_seen_chunk",
        "primary_role_function",
        "status",
        "source_confidence",
    ),
    "current_relations": (
        "relation_id",
        "from_name",
        "to_name",
        "relation_type",
        "first_seen_chunk",
        "last_seen_chunk",
        "latest_event_id",
        "is_active",
    ),
    "relation_events": (
        "relation_event_id",
        "chunk_id",
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "change_type",
        "evidence",
        "confidence",
        "directionality",
        "source_relation_row_id",
    ),
}


@dataclass(slots=True)
class GraphAuthorityReport:
    """
    Narrow authority-owned graph signals for non-graph product consumers.

    Export and diagnosis may reuse these aggregate graph signals as inputs, but
    the final diagnosis/aggregate conclusions are assembled outside authority.
    The quality payload is intentionally aggregate-only so these consumers do
    not recouple to graph page detail samples through report-level shortcuts.
    """

    summary: GraphSharedSummary = field(default_factory=GraphSharedSummary)
    quality: GraphQualitySignals = field(default_factory=GraphQualitySignals)

    def __post_init__(self) -> None:
        # 中文注释：GraphAuthorityReport 是 diagnosis/export 共享边界，必须在
        # 运行时也拒绝 graph page contract，避免调用方误把页面高亮/样本塞回共享层。
        if type(self.summary) is not GraphSharedSummary:
            raise TypeError(
                "GraphAuthorityReport.summary must be GraphSharedSummary; "
                f"got {type(self.summary).__name__}"
            )
        if type(self.quality) is not GraphQualitySignals:
            raise TypeError(
                "GraphAuthorityReport.quality must be GraphQualitySignals; "
                f"got {type(self.quality).__name__}"
            )
