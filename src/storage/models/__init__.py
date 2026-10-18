"""统一导出 ORM 模型与 Base（2026-10-16 全库 3NF 改造后的 35 张目标基本表）

目标库恰 35 张物理基本表（35 为全库上限，含审计、案例、证据、消息与全部辅助
持久化表）。已退场的旧关系（analysis_outputs、model_turns、annotation_work、
diagnosis_works、paragraph_linguistic_features、paragraph_curves、global_stats、
paragraph_embeddings、paragraph_pos_embeddings、paragraph_entities、
paragraph_phrase_hits、paragraph_topic_inference、word2vec_model_runs、
topic_model_runs、event_nodes、event_containments、event_outcomes、
event_outcome_links、event_arc_links、event_relations、event_declaration_bindings、
event_narrative_arcs、event_memberships、event_references、entity_states、
relation_states、event_edges 等）不在本导出中；其事实均有明确新落点。
"""

from src.storage.models.agent_audit import AgentToolCall, EventOutbox, ModelCall
from src.storage.models.base import Base, naive_utcnow
from src.storage.models.case_pool import BookCase, CaseEntry
from src.storage.models.chapter import Chapter
from src.storage.models.core import AnalysisRun
from src.storage.models.dialogue import DialogueRecord
from src.storage.models.event_forest import (
    CompleteEvent,
    DeclarationParticipant,
    EventDeclaration,
    EventRevision,
)
from src.storage.models.graph import FactEntityTag, GraphEntity, GraphFact, GraphRelation
from src.storage.models.linguistic import LinguisticArc, LinguisticSpan
from src.storage.models.novel import Novel
from src.storage.models.organization import (
    ConflictClaim,
    ConflictRecord,
    EventForeshadowingAction,
    NarrativeGroup,
    NarrativeLink,
    OrganizationCheck,
    SourceEvidence,
)
from src.storage.models.paragraph import Paragraph
from src.storage.models.paragraph_features import ParagraphFeature
from src.storage.models.paragraph_metrics import ParagraphMetric
from src.storage.models.paragraph_topics import ParagraphTopic
from src.storage.models.work import (
    ANNOTATION_ROLES,
    DIAGNOSIS_ROLES,
    EXECUTION_ROLES,
    AnalysisAssessment,
    ChapterAnnotation,
    DiagnosisReport,
    Execution,
    WorkItem,
)

__all__ = [
    "AgentToolCall",
    "ANNOTATION_ROLES",
    "AnalysisAssessment",
    "AnalysisRun",
    "Base",
    "BookCase",
    "CaseEntry",
    "Chapter",
    "ChapterAnnotation",
    "CompleteEvent",
    "ConflictClaim",
    "ConflictRecord",
    "DeclarationParticipant",
    "DIAGNOSIS_ROLES",
    "DiagnosisReport",
    "DialogueRecord",
    "EventDeclaration",
    "EventForeshadowingAction",
    "EventOutbox",
    "EventRevision",
    "EXECUTION_ROLES",
    "Execution",
    "FactEntityTag",
    "GraphEntity",
    "GraphFact",
    "GraphRelation",
    "LinguisticArc",
    "LinguisticSpan",
    "ModelCall",
    "NarrativeGroup",
    "NarrativeLink",
    "Novel",
    "OrganizationCheck",
    "Paragraph",
    "ParagraphFeature",
    "ParagraphMetric",
    "ParagraphTopic",
    "SourceEvidence",
    "WorkItem",
    "naive_utcnow",
]
