from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# 以下 allowlist 常量把 authority 输出矩阵直接固定在代码里
# consumer 只能依赖自己那一层明确允许的字段，避免继续跨层借字段
LEVEL1_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
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
        "latest_relation_version_id",
        "tension_index",
    ),
    "entity_types": ("name", "entity_type"),
}


@dataclass(slots=True)
class CanonicalEntity:
    """
    单次运行内稳定的实体身份

    这里刻意排除 `last_action`、`last_emotion_score` 这类 prompt 局部瞬时状态，
    以保证 Level 1 始终是最小且可复用的 authority 合同
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
    """单个关系对的当前 authority 快照，不包含历史事件"""

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
    latest_relation_version_id: int | None = None
    tension_index: float | None = None
    source: str = "graph_relation_versions"


@dataclass(slots=True)
class GraphChange:
    """2026-08-07 用于向章节版本消费者传递事实原因与双源 Evidence"""

    change_id: str
    change_kind: str
    graph_version_id: str
    chapter_id: int
    chapter_order: int
    fact_id: str
    fact_revision: int
    effective_chunk_id: int
    confidence: str
    changes: list[dict]
    evidence: list[dict]
    entity_id: int | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    relation_id: str | None = None
    relation_version_id: int | None = None
    relation_revision: int | None = None
    from_entity_id: int | None = None
    to_entity_id: int | None = None
    from_name: str | None = None
    to_name: str | None = None
    relation_type: str | None = None
    directionality: str | None = None
    relation_semantics: str | None = None
    source: str = "chapter_graph_versions"


@dataclass(slots=True)
class EntityTypeFact:
    name: str
    entity_type: str
    source: str = "graph_entities"


@dataclass(slots=True)
class EntityLifecycle:
    """
    可安全复用于不同消费者的稳定生命周期元数据

    对时间轴消费者来说，这里是角色进出场区间的受保护真相源。
    下游代码不应再从 repository 原始行重新推导生命周期窗口
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
    附近活跃实体的 Level 2 局部上下文合同

    这样既能让 prompt 消费者摆脱 repository 行结构，
    又能暴露标注/消歧所需的最近局部状态
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
class ParticipantState:
    """
    跨 chunk 复用的稳定实体状态

    这里刻意排除 `last_action`、局部情绪等瞬时局部上下文
    """

    entity_id: int
    name: str
    entity_type: str
    status: str = "active"
    primary_role_function: str | None = None
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    source_confidence: float | None = None
    is_representative: bool = True
    source: str = "graph_facts"


@dataclass(slots=True)
class Level1AuthoritySnapshot:
    """
    面向实体关系消费者的最小 authority 合同

    该快照用于共享实体与关系读取
    不混入时间轴历史、图谱产品摘要或 prompt 局部状态
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    entity_types: list[EntityTypeFact] = field(default_factory=list)


# timeline 只允许消费角色子图、生命周期与章节图变化三块共享字段，
# 不允许从 GraphAuthorityView 或 repository 原始形状反推历史语义
TIMELINE_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "character_entities": ("entity_id", "name", "entity_type"),
    "entity_lifecycles": ("entity_id", "name", "entity_type", "first_seen_chunk", "last_seen_chunk"),
    "graph_changes": (
        "change_id",
        "change_kind",
        "graph_version_id",
        "chapter_id",
        "chapter_order",
        "fact_id",
        "fact_revision",
        "effective_chunk_id",
        "changes",
        "evidence",
        "entity_id",
        "entity_name",
        "from_entity_id",
        "to_entity_id",
        "from_name",
        "to_name",
        "relation_type",
        "directionality",
    ),
}


@dataclass(slots=True)
class TimelineAuthorityView:
    """
    面向时间轴的受保护 authority 合同

    这个视图刻意比完整图谱 authority 面更窄：
    - `character_entities` 只包含角色子图
    - `entity_lifecycles` 与同一批角色集合保持一致
    - `graph_changes` 包含角色状态变化与角色子图关系变化

    时间轴消费者应把这里当作共享合同，
    不要依赖 repository 行结构或数据库图内部关系表
    """

    character_entities: list[CanonicalEntity] = field(default_factory=list)
    entity_lifecycles: list[EntityLifecycle] = field(default_factory=list)
    graph_changes: list[GraphChange] = field(default_factory=list)


# graph page route assembler 只允许读取这三块 authority facts
# 页面 summary / quality / events_page 仍由 route/product 层自己组装
GRAPH_PAGE_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "participant_states": (
        "entity_id",
        "name",
        "entity_type",
        "status",
        "primary_role_function",
        "first_seen_chunk",
        "last_seen_chunk",
        "is_representative",
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
    "graph_changes": (
        "change_id",
        "change_kind",
        "graph_version_id",
        "chapter_id",
        "fact_id",
        "fact_revision",
        "changes",
        "evidence",
    ),
}


@dataclass(slots=True)
class GraphAuthorityView:
    """
    面向图谱页面的受保护 authority 事实

    该合同故意只停留在稳定事实层：
    - canonical 实体身份
    - 当前已确认关系
    - 完整且不可变的章节实体与关系变化
    - 参与者实体状态

    产品层摘要/质量卡片属于图谱页面组装层，
    diagnosis / aggregate 结论属于更高层分析。
    如果其他下游需要不同切片，应新增专用合同，
    不要借用 repository 行，也不要挤占实体关系与 Timeline 的边界
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    confirmed_relations: list[ConfirmedRelation] = field(default_factory=list)
    graph_changes: list[GraphChange] = field(default_factory=list)
    participant_states: list[ParticipantState] = field(default_factory=list)


@dataclass(slots=True)
class GraphSharedSummary:
    """
    在图谱产品面之外共享的聚合级图谱摘要

    diagnosis / export 可以把这些计数器复用为图谱侧输入信号，
    但核心角色、关键关系之类更丰富的高亮必须留在 graph-page-only 合同里
    """

    node_count: int = 0
    edge_count: int = 0
    density: float = 0.0

    def to_contract_dict(self) -> dict[str, float | int]:
        """按显式字段白名单序列化共享图谱摘要"""

        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "density": self.density,
        }


@dataclass(slots=True)
class GraphQualitySignals:
    """
    在图谱页面之外共享的聚合级图谱质量计数器

    详细的冲突样本 / 低置信样本属于图谱产品展示层，
    不应继续流入 diagnosis / export / aggregate 层
    """

    conflict_count: int = 0
    low_confidence_count: int = 0

    def to_contract_dict(self) -> dict[str, int]:
        """按显式字段白名单序列化共享图谱质量计数器"""

        return {
            "conflict_count": self.conflict_count,
            "low_confidence_count": self.low_confidence_count,
        }


# report 只给 diagnosis/export 共用聚合信号，字段必须保持最小集
GRAPH_REPORT_AUTHORITY_DEPENDENCY_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "summary": ("node_count", "edge_count", "density"),
    "quality": ("conflict_count", "low_confidence_count"),
}


@dataclass(slots=True)
class GraphKeyRelationHighlight:
    """页面展示用的单条代表性已确认关系高亮"""

    from_name: str
    to_name: str
    relation_type: str | None = None
    support_count: int = 0


@dataclass(slots=True)
class GraphPageSummary:
    """
    仅供图谱页面使用的摘要合同

    这里可以承载页面首屏高亮（如核心角色、关键关系），但这些字段
    不应进入 diagnosis/export/shared signals，否则 graph page 又会反向定义
    上层分析语义
    """

    node_count: int = 0
    edge_count: int = 0
    density: float = 0.0
    core_characters: list[str] = field(default_factory=list)
    key_relations: list[GraphKeyRelationHighlight] = field(default_factory=list)


@dataclass(slots=True)
class GraphConflictSample:
    """仅供图谱页面展示的关系类型冲突样本"""

    entity_pair: list[int | None] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    relation_count: int = 0
    latest_relation_version_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class GraphLowConfidenceSample:
    """仅供图谱页面展示的单条低置信关系变化样本"""

    change_id: str
    graph_version_id: str
    chapter_id: int
    fact_id: str
    fact_revision: int
    effective_chunk_id: int
    relation_id: str | None
    from_name: str
    to_name: str
    relation_type: str | None = None
    change_kind: str | None = None
    confidence: str | None = None


@dataclass(slots=True)
class GraphPageQualityDetails:
    """
    仅供图谱页面使用的质量明细

    共享层只拿 counters；样本明细只服务 graph page 的排障与解释，
    不允许 diagnosis/export 继续顺手复用这些字段
    """

    conflict_count: int = 0
    low_confidence_count: int = 0
    conflicts: list[GraphConflictSample] = field(default_factory=list)
    low_confidence_samples: list[GraphLowConfidenceSample] = field(default_factory=list)


@dataclass(slots=True)
class ExportRelationSnapshot:
    """专供结果导出 payload 组装的当前关系快照"""

    relation_id: str | None = None
    from_name: str = ""
    to_name: str = ""
    relation_type: str = ""
    first_seen_chunk: int | None = None
    last_seen_chunk: int | None = None
    relation_version_id: int | None = None
    is_active: bool = True
    source: str = "graph_relation_versions"


@dataclass(slots=True)
class ExportGraphAuthorityView:
    """
    专供图谱导出 payload 的 authority 视图

    结果导出仍会输出 chunk 级关系、层级关系摘要等 DTO。
    该视图让这些 payload 构建器脱离 repository 内部行结构，
    同时避免把仅导出相关的关注点塞进 `GraphAuthorityView` 或 `GraphAuthorityReport`
    """

    canonical_entities: list[CanonicalEntity] = field(default_factory=list)
    current_relations: list[ExportRelationSnapshot] = field(default_factory=list)
    graph_changes: list[GraphChange] = field(default_factory=list)


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
        "relation_version_id",
        "is_active",
    ),
    "graph_changes": (
        "change_id",
        "change_kind",
        "graph_version_id",
        "chapter_id",
        "fact_id",
        "fact_revision",
        "changes",
        "evidence",
    ),
}


@dataclass(slots=True)
class GraphAuthorityReport:
    """
    面向非图谱产品消费者的精简 authority 图谱信号

    export 与 diagnosis 可以复用这些聚合图谱信号作为输入，
    但最终 diagnosis / aggregate 结论仍在 authority 之外组装。
    质量 payload 也刻意只保留聚合结果，
    避免调用方通过 report 级捷径重新耦合到图谱页面的明细样本
    """

    summary: GraphSharedSummary = field(default_factory=GraphSharedSummary)
    quality: GraphQualitySignals = field(default_factory=GraphQualitySignals)

    def __post_init__(self) -> None:
        # GraphAuthorityReport 是 diagnosis/export 共享边界，必须在
        # 运行时也拒绝 graph page contract，避免调用方误把页面高亮/样本塞回共享层
        if type(self.summary) is not GraphSharedSummary:
            raise TypeError(
                f"GraphAuthorityReport.summary must be GraphSharedSummary; got {type(self.summary).__name__}"
            )
        if type(self.quality) is not GraphQualitySignals:
            raise TypeError(
                f"GraphAuthorityReport.quality must be GraphQualitySignals; got {type(self.quality).__name__}"
            )
