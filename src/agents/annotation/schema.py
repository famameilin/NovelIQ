"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, JsonValue, RootModel, model_validator


class StrictModel(BaseModel):
    """2026-08-07 用于统一拒绝标注合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


class EmotionalValence(StrEnum):
    """2026-08-07 用于约束情绪方向与强度"""

    STRONG_POSITIVE = "strong_positive"
    MILD_POSITIVE = "mild_positive"
    NEUTRAL = "neutral"
    MILD_NEGATIVE = "mild_negative"
    STRONG_NEGATIVE = "strong_negative"


class NarrativeFunction(StrEnum):
    """2026-08-07 用于约束 chunk 在叙事结构中的功能"""

    CONFLICT = "冲突"
    SETUP = "铺垫"
    TURNING_POINT = "转折"


class Confidence(StrEnum):
    """2026-08-07 用于约束 Agent 语义判断置信度"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RoleFunction(StrEnum):
    """2026-08-07 用于约束人物在当前叙事动作中的功能"""

    SUBJECT = "主体"
    OBJECT = "客体"
    SENDER = "发送者"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"


class ActionType(StrEnum):
    """2026-08-07 用于约束人物动作的宽口径类别"""

    COMBAT = "战斗"
    ESCAPE = "逃跑"
    DIALOGUE = "对话"
    DECISION = "决策"
    MOVEMENT = "移动"
    EMOTION = "情感"
    OTHER = "其他"


class Assertion(StrEnum):
    """2026-08-07 用于约束状态事实肯定或否定"""

    AFFIRMED = "affirmed"
    NEGATED = "negated"


class RelationChangeKind(StrEnum):
    """2026-08-07 用于约束关系事实的生命周期变化"""

    ASSERT = "assert"
    REINFORCE = "reinforce"
    WEAKEN = "weaken"
    BREAK = "break"
    REFINE = "refine"
    SUPERSEDE = "supersede"
    RETRACT = "retract"


class RelationType(StrEnum):
    """2026-08-07 用于提供唯一闭合关系类型注册表"""

    FAMILY = "家族"
    MASTER_DISCIPLE = "师徒"
    HOSTILE = "敌对"
    ALLY = "盟友"
    FRIENDSHIP = "友情"
    AFFECTION = "爱慕"
    MASTER_SERVANT = "主从"
    INTEREST = "利益"
    SAME_CHARACTER = "同一人物"
    BELONGS_TO = "belongs_to"
    MEMBER_OF = "member_of"
    LEADER_OF = "leader_of"
    AFFILIATED_WITH = "affiliated_with"
    FATHER_OF = "father_of"
    SON_OF = "son_of"
    PARENT_OF = "parent_of"
    CHILD_OF = "child_of"
    SIBLING_OF = "sibling_of"
    SPOUSE_OF = "spouse_of"
    LOCATED_AT = "located_at"
    ENTERED = "entered"
    ARRIVED_AT = "arrived_at"
    INSIDE = "inside"
    LEFT = "left"
    DEPARTED_FROM = "departed_from"


class ForeshadowingType(StrEnum):
    """2026-08-07 用于约束伏笔载体类别"""

    OBJECT = "物件"
    DIALOGUE = "对话"
    SCENE = "场景"
    CHARACTER_ACTION = "人物行为"
    OTHER = "其他"


class SetupKind(StrEnum):
    """2026-08-07 用于约束伏笔 setup 的宽口径类别"""

    ABNORMAL_OBJECT = "异常物件"
    ABNORMAL_RULE = "异常规则"
    HIDDEN_IDENTITY = "隐藏身份"
    EXPLICIT_PROMISE = "明确承诺"
    EXPLICIT_THREAT = "明确威胁"
    COUNTDOWN = "倒计时"
    UNEXPLAINED_ABILITY = "未解释能力"
    CAUSAL_TRIGGER = "因果引线"
    OTHER = "其他"


class SetupStatus(StrEnum):
    """2026-08-07 用于约束伏笔线程当前阶段"""

    OPEN = "open"
    REINFORCED = "reinforced"
    LIKELY_PAID_OFF = "likely_paid_off"


class PayoffLikelihood(StrEnum):
    """2026-08-07 用于约束伏笔回收可能性"""

    HIGH = "high"
    MEDIUM = "medium"


EntityType = Literal["character", "location", "object", "organization"]
Directionality = Literal["directed", "bidirectional"]
RelationSemantics = Literal["ordinary", "same_character"]
CaseType = Literal["dialogue_speaker"]
CaseState = Literal["active", "resolved"]
DialogueParseStatus = Literal["paired_quote", "dialogue_line", "unclosed_quote"]

_ALL_ENTITY_TYPES: tuple[EntityType, ...] = (
    "character",
    "location",
    "object",
    "organization",
)
_ACTOR_ENTITY_TYPES: tuple[EntityType, ...] = ("character", "organization")
_CHARACTER_ENTITY_TYPES: tuple[EntityType, ...] = ("character",)
_LOCATION_ENTITY_TYPES: tuple[EntityType, ...] = ("location",)
_MOBILE_ENTITY_TYPES: tuple[EntityType, ...] = (
    "character",
    "object",
    "organization",
)


class RelationDefinition(TypedDict):
    """2026-08-07 用于集中定义关系方向端点类型和关系语义"""

    directionality: Directionality
    semantics: RelationSemantics
    from_types: tuple[EntityType, ...]
    to_types: tuple[EntityType, ...]


RELATION_DEFINITIONS: dict[str, RelationDefinition] = {
    "家族": {
        "directionality": "bidirectional",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "师徒": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "敌对": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": _ACTOR_ENTITY_TYPES,
    },
    "盟友": {
        "directionality": "bidirectional",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": _ACTOR_ENTITY_TYPES,
    },
    "友情": {
        "directionality": "bidirectional",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "爱慕": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "主从": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "利益": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": _ACTOR_ENTITY_TYPES,
    },
    "同一人物": {
        "directionality": "bidirectional",
        "semantics": "same_character",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "belongs_to": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ALL_ENTITY_TYPES,
        "to_types": _ALL_ENTITY_TYPES,
    },
    "member_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": ("organization",),
    },
    "leader_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": ("organization",),
    },
    "affiliated_with": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": ("organization",),
    },
    "father_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "son_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "parent_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "child_of": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "sibling_of": {
        "directionality": "bidirectional",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "spouse_of": {
        "directionality": "bidirectional",
        "semantics": "ordinary",
        "from_types": _CHARACTER_ENTITY_TYPES,
        "to_types": _CHARACTER_ENTITY_TYPES,
    },
    "located_at": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _MOBILE_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
    "entered": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _MOBILE_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
    "arrived_at": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _MOBILE_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
    "inside": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ALL_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
    "left": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _MOBILE_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
    "departed_from": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _MOBILE_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
}


def normalize_semantic_text(value: str, *, label: str) -> str:
    """2026-08-07 用于统一规范化 Agent 提交的人类可读文本"""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    return normalized


class GraphEvidence(StrictModel):
    """2026-08-07 用于系统内部保存前序图事实依据"""

    fact_id: str = Field(min_length=1)
    fact_revision: int = Field(gt=0)
    reason: str = Field(min_length=1)


class TextEvidence(StrictModel):
    """2026-08-07 用于系统内部保存真实原文依据"""

    reason: str = Field(min_length=1)
    chunk_id: int = Field(ge=0)


Evidence = GraphEvidence | TextEvidence


class EvidenceList(RootModel[list[Evidence]]):
    """2026-08-07 用于保证持久化事实至少具有一条系统依据"""

    root: list[Evidence] = Field(min_length=1)

    def __iter__(self):
        """2026-08-07 用于按系统绑定顺序遍历依据"""
        return iter(self.root)

    def __len__(self) -> int:
        """2026-08-07 用于返回系统依据数量"""
        return len(self.root)

    def __getitem__(self, index: int) -> Evidence:
        """2026-08-07 用于按位置读取系统依据"""
        return self.root[index]


class StoryTime(StrictModel):
    """2026-08-07 用于表达故事内时间而不混入处理顺序"""

    label: str | None = None
    order: int | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> StoryTime:
        """2026-08-07 用于拒绝没有任何语义字段的故事时间"""
        if not self.model_fields_set:
            raise ValueError("story_time 至少需要一个字段")
        return self


class SemanticItem(StrictModel):
    """2026-08-07 用于统一 Agent 语义判断的置信度和解释"""

    confidence: Confidence
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_reason(self) -> SemanticItem:
        """2026-08-07 用于规范化并校验语义判断说明"""
        self.reason = normalize_semantic_text(self.reason, label="reason")
        return self


class EntityInput(SemanticItem):
    """2026-08-07 用于提交当前 chunk 明确出现的实体"""

    name: str = Field(min_length=1)
    description: str | None = None

    @model_validator(mode="after")
    def normalize_entity(self) -> EntityInput:
        """2026-08-07 用于规范化实体名称和可选描述"""
        self.name = normalize_semantic_text(self.name, label="entity.name")
        if self.description is not None:
            self.description = normalize_semantic_text(
                self.description,
                label="entity.description",
            )
        return self


class EntityDirectoryInput(StrictModel):
    """2026-08-07 用于按实体大类提交当前 chunk 出现目录"""

    characters: list[EntityInput] = Field(default_factory=list)
    locations: list[EntityInput] = Field(default_factory=list)
    objects: list[EntityInput] = Field(default_factory=list)
    organizations: list[EntityInput] = Field(default_factory=list)


class ChunkMetricsInput(SemanticItem):
    """2026-08-07 用于提交当前 chunk 摘要和叙事指标"""

    summary: str = Field(min_length=1)
    emotional_valence: EmotionalValence
    narrative_function: NarrativeFunction
    pivot_moment: bool = False
    cliffhanger: bool = False

    @model_validator(mode="after")
    def normalize_summary(self) -> ChunkMetricsInput:
        """2026-08-07 用于规范化当前 chunk 摘要"""
        self.summary = normalize_semantic_text(self.summary, label="summary")
        return self


class CharacterObservationInput(SemanticItem):
    """2026-08-07 用于提交人物在当前 chunk 的动作和功能"""

    character: str = Field(min_length=1)
    role_function: RoleFunction
    action: str = Field(min_length=1)
    action_type: ActionType
    emotion: EmotionalValence

    @model_validator(mode="after")
    def normalize_character_observation(self) -> CharacterObservationInput:
        """2026-08-07 用于规范化人物名称和动作说明"""
        self.character = normalize_semantic_text(self.character, label="character")
        self.action = normalize_semantic_text(self.action, label="action")
        return self


class DialogueInput(SemanticItem):
    """2026-08-07 用于按系统候选顺序提交对话语义判断"""

    is_dialogue: bool
    description: str | None = None
    speaker: str | None = None
    tone: str | None = None
    is_inner_monologue: bool = False

    @model_validator(mode="after")
    def validate_dialogue(self) -> DialogueInput:
        """2026-08-07 用于约束有效对话和误判候选的字段组合"""
        if self.is_dialogue:
            if self.description is None:
                raise ValueError("有效对话必须提供 description")
            self.description = normalize_semantic_text(
                self.description,
                label="dialogue.description",
            )
            if self.speaker is not None:
                self.speaker = normalize_semantic_text(
                    self.speaker,
                    label="dialogue.speaker",
                )
            if self.tone is not None:
                self.tone = normalize_semantic_text(self.tone, label="dialogue.tone")
            return self
        if any(
            value is not None
            for value in (self.description, self.speaker, self.tone)
        ) or self.is_inner_monologue:
            raise ValueError("非对话候选只能提交判断结果置信度和 reason")
        return self


class EventParticipantInput(StrictModel):
    """2026-08-07 用于描述实体如何参与当前事件"""

    entity: str = Field(min_length=1)
    participation: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_participant(self) -> EventParticipantInput:
        """2026-08-07 用于规范化参与实体和参与方式"""
        self.entity = normalize_semantic_text(self.entity, label="event.participant.entity")
        self.participation = normalize_semantic_text(
            self.participation,
            label="event.participant.participation",
        )
        return self


class EventInput(SemanticItem):
    """2026-08-07 用于提交不依赖任意 event_type 的事件描述"""

    description: str = Field(min_length=1)
    participants: list[EventParticipantInput] = Field(default_factory=list)
    location: str | None = None
    story_time: StoryTime | None = None

    @model_validator(mode="after")
    def normalize_event(self) -> EventInput:
        """2026-08-07 用于规范化事件说明和可选地点"""
        self.description = normalize_semantic_text(
            self.description,
            label="event.description",
        )
        if self.location is not None:
            self.location = normalize_semantic_text(
                self.location,
                label="event.location",
            )
        return self


class RelationInput(SemanticItem):
    """2026-08-07 用于通过实体名称提交闭合类型关系变化"""

    from_entity: str = Field(min_length=1)
    to_entity: str = Field(min_length=1)
    relation_type: RelationType
    change_kind: RelationChangeKind

    @model_validator(mode="after")
    def normalize_relation(self) -> RelationInput:
        """2026-08-07 用于规范化关系两端实体名称"""
        self.from_entity = normalize_semantic_text(
            self.from_entity,
            label="relation.from_entity",
        )
        self.to_entity = normalize_semantic_text(
            self.to_entity,
            label="relation.to_entity",
        )
        if self.from_entity == self.to_entity:
            raise ValueError("关系两端不能是同一名称")
        return self


class StateInput(SemanticItem):
    """2026-08-07 用于提交实体当前状态及可选实体对象"""

    entity: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str | None = None
    value: JsonValue | None = None
    story_time: StoryTime | None = None
    assertion: Assertion = Assertion.AFFIRMED

    @model_validator(mode="after")
    def validate_state(self) -> StateInput:
        """2026-08-07 用于规范化状态并保证 object 与 value 二选一"""
        self.entity = normalize_semantic_text(self.entity, label="state.entity")
        self.predicate = normalize_semantic_text(self.predicate, label="state.predicate")
        if self.object is not None:
            self.object = normalize_semantic_text(self.object, label="state.object")
        if (self.object is None) == (self.value is None):
            raise ValueError("state.object 与 state.value 必须恰好一个非空")
        return self


class ForeshadowingInput(SemanticItem):
    """2026-08-07 用于通过稳定语义字段提交伏笔线程变化"""

    foreshadowing_type: ForeshadowingType
    setup_kind: SetupKind
    setup_summary: str = Field(min_length=1)
    why_unresolved_now: str = Field(min_length=1)
    expected_payoff_family: str = Field(min_length=1)
    payoff_likelihood: PayoffLikelihood
    setup_status: SetupStatus

    @model_validator(mode="after")
    def normalize_foreshadowing(self) -> ForeshadowingInput:
        """2026-08-07 用于规范化伏笔稳定字段和未解决原因"""
        self.setup_summary = normalize_semantic_text(
            self.setup_summary,
            label="foreshadowing.setup_summary",
        )
        self.expected_payoff_family = normalize_semantic_text(
            self.expected_payoff_family,
            label="foreshadowing.expected_payoff_family",
        )
        self.why_unresolved_now = normalize_semantic_text(
            self.why_unresolved_now,
            label="foreshadowing.why_unresolved_now",
        )
        return self


class DialogueCandidate(StrictModel):
    """2026-08-07 用于系统保存对话候选真实原文和位置"""

    candidate_key: str = Field(min_length=1)
    chunk_id: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    content: str = Field(min_length=1)
    parse_status: DialogueParseStatus

    @model_validator(mode="after")
    def validate_bounds(self) -> DialogueCandidate:
        """2026-08-07 用于拒绝倒置或空的系统对话区间"""
        if self.end <= self.start:
            raise ValueError("dialogue candidate end 必须大于 start")
        return self


class BoundEntity(SemanticItem):
    """2026-08-07 用于系统绑定当前 chunk 实体出现及文本依据"""

    name: str
    description: str | None = None
    evidence: EvidenceList


class BoundEntityDirectory(StrictModel):
    """2026-08-07 用于保存当前 chunk 四类实体出现"""

    characters: list[BoundEntity] = Field(default_factory=list)
    locations: list[BoundEntity] = Field(default_factory=list)
    objects: list[BoundEntity] = Field(default_factory=list)
    organizations: list[BoundEntity] = Field(default_factory=list)


class BoundCharacterObservation(CharacterObservationInput):
    """2026-08-07 用于系统绑定人物观察文本依据"""

    evidence: EvidenceList


class BoundDialogue(SemanticItem):
    """2026-08-07 用于系统绑定有效对话原文位置和语义结果"""

    candidate_key: str
    content: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    description: str
    speaker: str | None = None
    tone: str | None = None
    is_inner_monologue: bool = False
    evidence: EvidenceList


class BoundEvent(EventInput):
    """2026-08-07 用于系统绑定事件文本依据"""

    evidence: EvidenceList


class BoundRelation(RelationInput):
    """2026-08-07 用于系统注入关系方向和语义元数据"""

    directionality: Directionality
    relation_semantics: RelationSemantics
    evidence: EvidenceList


class BoundState(StateInput):
    """2026-08-07 用于系统绑定状态文本依据"""

    evidence: EvidenceList


class BoundForeshadowing(ForeshadowingInput):
    """2026-08-07 用于系统绑定伏笔文本依据"""

    evidence: EvidenceList


class BoundChunkAnnotation(StrictModel):
    """2026-08-07 用于保存系统完成绑定的单个 chunk 正式标注"""

    chunk_id: int = Field(ge=0)
    metrics: ChunkMetricsInput
    entities: BoundEntityDirectory
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    relations: list[BoundRelation]
    states: list[BoundState]
    foreshadowings: list[BoundForeshadowing]


class BoundChapterAnnotation(StrictModel):
    """2026-08-07 用于保存最新语义写入合同的章节正式标注"""

    contract_version: Literal["agent-semantic-v1"] = "agent-semantic-v1"
    chapter_summary: str = Field(min_length=1)
    chunks: list[BoundChunkAnnotation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_chapter(self) -> BoundChapterAnnotation:
        """2026-08-07 用于规范化摘要并保证 chunk 顺序唯一"""
        self.chapter_summary = normalize_semantic_text(
            self.chapter_summary,
            label="chapter_summary",
        )
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("章节标注 chunk_id 不允许重复")
        return self


class TextSearchResult(StrictModel):
    """2026-08-07 用于查询服务返回真实原文定位结果"""

    chapter_id: int = Field(gt=0)
    chunk_id: int = Field(ge=0)
    excerpt: str
    keyword_score: float = Field(ge=0)
    semantic_score: float | None = None


class GraphSearchFact(StrictModel):
    """2026-08-07 用于查询服务内部保存可见图事实版本"""

    fact_id: str
    fact_revision: int = Field(gt=0)
    fact_type: str
    predicate: str
    effective_chunk_id: int = Field(ge=0)
    content: dict[str, Any]
    evidence: EvidenceList


class GraphSearchEntity(StrictModel):
    """2026-08-07 用于查询服务内部保存可见实体状态"""

    entity_id: int = Field(gt=0)
    name: str
    entity_type: EntityType
    state_revision: int = Field(ge=0)
    state: dict[str, Any] = Field(default_factory=dict)


class GraphSearchRelation(StrictModel):
    """2026-08-07 用于查询服务内部保存可见稳定关系"""

    relation_id: str
    relation_revision: int = Field(gt=0)
    from_entity_id: int = Field(gt=0)
    to_entity_id: int = Field(gt=0)
    from_name: str
    to_name: str
    relation_type: str
    directionality: Directionality
    relation_semantics: RelationSemantics
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool


class GraphSearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回上一章节图快照"""

    graph_version_id: str
    facts: list[GraphSearchFact] = Field(default_factory=list)
    entities: list[GraphSearchEntity] = Field(default_factory=list)
    relations: list[GraphSearchRelation] = Field(default_factory=list)
    paths: list[list[str]] = Field(default_factory=list)


class CaseSearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回活动连续性案例"""

    id: str = Field(min_length=1)
    type: CaseType
    chunk_id: int = Field(ge=0)
    keys: list[str] = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=100)
    evidence: EvidenceList
    state: Literal["active"] = "active"


class ActiveCaseDetails(CaseSearchResult):
    """2026-08-07 用于系统内部携带案例稳定目标"""

    target_key: str = Field(min_length=1)
    target_ref: dict[str, Any]


class ForeshadowingSearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回伏笔线程"""

    record_id: str
    content: dict[str, Any]
    evidence: EvidenceList


SearchResultItem = Annotated[
    CaseSearchResult | ForeshadowingSearchResult,
    Field(union_mode="left_to_right"),
]


class SearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回案例与伏笔结果"""

    results: list[SearchResultItem] = Field(default_factory=list, max_length=50)


class ResolvedCase(StrictModel):
    """2026-08-07 用于系统暂存 Agent 对活动案例的语义解决结果"""

    case_id: str
    type: CaseType
    speaker: str
    reason: str
    evidence_chunk_id: int = Field(ge=0)
    target_key: str
    target_ref: dict[str, Any]


class PendingCase(StrictModel):
    """2026-08-07 用于系统自动保存当前未确认对话案例"""

    type: CaseType = "dialogue_speaker"
    chunk_id: int = Field(ge=0)
    keys: list[str] = Field(min_length=1)
    description: str
    target_key: str
    target_ref: dict[str, Any]
    evidence: EvidenceList


class SuccessAudit(StrictModel):
    """2026-08-07 用于保存成功模型调用和工具批次审计"""

    attempt_number: int = Field(ge=1, le=3)
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    model_name: str | None = None
    model_provider: str
    duration_ms: int = Field(ge=0)


class TokenUsageRecord(StrictModel):
    """2026-08-07 用于保存可信模型 Token 用量"""

    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class AgentRunAudit(StrictModel):
    """2026-08-07 用于保存系统范围搜索凭据和领域修订记录"""

    allow_future_context: bool
    write_revisions: list[dict[str, Any]]
    rotation_case_ids: list[str]
    authorized_text_chunk_ids: list[int]
    success: SuccessAudit
    token_usage: list[TokenUsageRecord] = Field(default_factory=list)


class AgentRunResult(StrictModel):
    """2026-08-07 用于承载章节 Agent 完成后的正式系统结果"""

    run_id: str
    chapter_id: int = Field(gt=0)
    annotation: BoundChapterAnnotation
    resolved_cases: list[ResolvedCase]
    pending_cases: list[PendingCase]
    audit: AgentRunAudit


class CompletionCase(StrictModel):
    """2026-08-07 用于返回完成事务实际创建的案例"""

    id: str
    type: CaseType
    chunk_id: int = Field(ge=0)
    keys: list[str]
    description: str
    target_ref: dict[str, Any]
    evidence: EvidenceList
    state: CaseState


class CompletionResolvedCase(StrictModel):
    """2026-08-07 用于返回完成事务写入的案例解决事实版本"""

    case_id: str
    type: CaseType
    speaker: str
    reason: str
    target_fact_id: str
    target_fact_revision: int = Field(gt=0)


class CompletionResult(StrictModel):
    """2026-08-07 用于回读或返回章节唯一完成事务"""

    annotation_id: str
    graph_version_id: str
    chapter_id: int = Field(gt=0)
    created_cases: list[CompletionCase] = Field(default_factory=list)
    resolved_cases: list[CompletionResolvedCase] = Field(default_factory=list)
