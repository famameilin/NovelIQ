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
    """2026-08-09 用于提供唯一闭合关系类型注册表（精简中文词表）"""

    FAMILY = "家族"
    MASTER_DISCIPLE = "师徒"
    MASTER_SERVANT = "主从"
    HOSTILE = "敌对"
    ALLY = "盟友"
    FRIENDSHIP = "友情"
    AFFECTION = "爱慕"
    INTEREST = "利益"
    SAME_CHARACTER = "同一人物"
    SUBORDINATION = "隶属"
    LOCATED = "位于"


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


EntityType = Literal["character", "location", "item", "organization"]
Directionality = Literal["directed", "bidirectional"]
RelationSemantics = Literal["ordinary", "same_character"]
CaseType = str
CaseAction = Literal["dialogue", "fact", "foreshadowing", "close"]
CaseState = Literal["active", "resolved"]
DialogueParseStatus = Literal["paired_quote", "dialogue_line", "unclosed_quote"]

_ACTOR_ENTITY_TYPES: tuple[EntityType, ...] = ("character", "organization")
_CHARACTER_ENTITY_TYPES: tuple[EntityType, ...] = ("character",)
_LOCATION_ENTITY_TYPES: tuple[EntityType, ...] = ("location",)
_MOBILE_ENTITY_TYPES: tuple[EntityType, ...] = (
    "character",
    "item",
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
    "主从": {
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
    "隶属": {
        "directionality": "directed",
        "semantics": "ordinary",
        "from_types": _ACTOR_ENTITY_TYPES,
        "to_types": ("organization",),
    },
    "位于": {
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

    confidence: Confidence = Field(description="本次判断的置信度：high/medium/low")
    reason: str = Field(min_length=1, description="判断依据，引用原文或上下文事实")

    @model_validator(mode="after")
    def normalize_reason(self) -> SemanticItem:
        """2026-08-07 用于规范化并校验语义判断说明"""
        self.reason = normalize_semantic_text(self.reason, label="reason")
        return self


class EntityInput(SemanticItem):
    """2026-08-08 用于提交当前 chunk 明确出现的实体"""

    name: str = Field(min_length=1, description="实体名称（新实体用本章出现的名称，已登记实体用登记名）")
    entity_type: EntityType = Field(
        description="实体大类：character=有生命的（含人/动物/灵兽/妖/器灵），item=无生命物品，"
        "location=地点，organization=组织；有生命就是 character，不要按戏份调整"
    )
    tags: list[str] = Field(
        default_factory=list,
        description="可空标签，最多 3 个，每个最多 5 个字，如\"灵兽\"\"剑灵\"\"法宝\"",
    )
    description: str | None = Field(
        default=None,
        description="实体一句话简介（已登记实体不要重复提交）",
    )

    @model_validator(mode="after")
    def normalize_entity(self) -> EntityInput:
        """2026-08-08 用于规范化实体名称、可选描述和自由标签"""
        self.name = normalize_semantic_text(self.name, label="entity.name")
        normalized_tags: list[str] = []
        for tag in self.tags:
            cleaned = unicodedata.normalize("NFC", tag).strip()
            if cleaned and cleaned not in normalized_tags:
                normalized_tags.append(cleaned)
        if len(normalized_tags) > 3:
            raise ValueError("entity.tags 最多 3 个标签")
        if any(len(tag) > 5 for tag in normalized_tags):
            raise ValueError("entity.tags 每个标签最多 5 个字")
        self.tags = normalized_tags
        if self.description is not None:
            self.description = normalize_semantic_text(
                self.description,
                label="entity.description",
            )
        return self


class EntityDirectoryInput(StrictModel):
    """2026-08-08 用于提交当前 chunk 出现的全部实体（单列表）"""

    entities: list[EntityInput] = Field(default_factory=list)


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

    character: str = Field(min_length=1, description="人物名称（已登记实体用登记名）")
    role_function: RoleFunction = Field(description="人物在本动作中的功能角色：主体/客体/发送者/接收者/帮助者/反对者")
    action: str = Field(min_length=1, description="动作描述，一句话概括人物做了什么")
    action_type: ActionType = Field(description="动作宽口径类别：战斗/逃跑/对话/决策/移动/情感/其他")
    emotion: EmotionalValence = Field(description="动作伴随的情绪方向与强度")

    @model_validator(mode="after")
    def normalize_character_observation(self) -> CharacterObservationInput:
        """2026-08-07 用于规范化人物名称和动作说明"""
        self.character = normalize_semantic_text(self.character, label="character")
        self.action = normalize_semantic_text(self.action, label="action")
        return self


class DialogueInput(SemanticItem):
    """2026-08-07 用于按系统候选顺序提交对话语义判断"""

    is_dialogue: bool = Field(description="该候选是否为真实对话；误判候选（如题字/内心描写被引号包裹）填 false")
    description: str | None = Field(
        default=None,
        description="有效对话的语义说明（is_dialogue=true 时必填）；误判候选必须留空",
    )
    speaker: str | None = Field(
        default=None,
        description="说话人名称（已登记实体用登记名）；无法确认说话人时留 null",
    )
    tone: str | None = Field(default=None, description="语气描述，如\"愤怒呵斥\"；误判候选必须留空")
    is_inner_monologue: bool = Field(
        default=False,
        description="是否为内心独白；误判候选必须为 false",
    )

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
            raise ValueError(
                "非对话候选只能提交判断结果置信度和 reason；"
                "含 action/emotion/role_function 的条目应提交到 write_character_observations"
            )
        return self


class DialogueSubmissionItem(BaseModel):
    """2026-08-09 用于宽容接收模型提交的对话判断（order 等多余字段直接忽略）"""

    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    is_dialogue: bool = Field(description="该候选是否为真实对话；误判候选（如题字/内心描写被引号包裹）填 false")
    description: str | None = Field(
        default=None,
        description="有效对话的语义说明（is_dialogue=true 时必填）；误判候选必须留空",
    )
    speaker: str | None = Field(
        default=None,
        description="说话人名称（已登记实体用登记名）；无法确认说话人时留 null",
    )
    tone: str | None = Field(default=None, description="语气描述，如\"愤怒呵斥\"；误判候选必须留空")
    is_inner_monologue: bool = Field(
        default=False,
        description="是否为内心独白；误判候选必须为 false",
    )
    confidence: Confidence = Field(description="本次判断的置信度：high/medium/low")
    reason: str = Field(min_length=1, description="判断依据，引用原文或上下文事实")


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

    from_entity: str = Field(min_length=1, description="关系起点实体（图上的登记名称）")
    to_entity: str = Field(min_length=1, description="关系终点实体（图上的登记名称）")
    relation_type: RelationType = Field(
        description="闭合关系类型：家族/师徒/主从/敌对/盟友/友情/爱慕/利益/同一人物/隶属/位于"
    )
    change_kind: RelationChangeKind = Field(
        description="变化类型：assert=新建关系；reinforce=强化已存在关系（要求图里已有该边）；"
        "break/retract=解除关系；refine=微调；supersede=取代；不确定边是否存在时用 assert"
    )

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

    entity: str = Field(min_length=1, description="状态主体（已登记实体用登记名）")
    predicate: str = Field(min_length=1, description="状态谓词，如\"伤势\"\"修为\"\"持有\"")
    object: str | None = Field(
        default=None,
        description="对象化状态内容（如\"白金离火\"\"玉戒尺\"\"封印血咒\"）；"
        "与 value 二选一，表达对象化存在时填此项",
    )
    value: JsonValue | None = Field(
        default=None,
        description="属性取值（如 6、\"重伤\"、\"初稳\"）；与 object 二选一，表达数值/取值时填此项",
    )
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
            raise ValueError(
                "state.object 与 state.value 必须恰好一个非空：object 填对象化存在"
                "（如\"白金离火\"\"玉戒尺\"），value 填属性取值（如数字/短句），拿不准优先填 object"
            )
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
    """2026-08-08 用于系统绑定当前 chunk 实体出现及文本依据"""

    name: str
    entity_type: EntityType
    tags: list[str] = Field(default_factory=list)
    description: str | None = None
    evidence: EvidenceList


class BoundEntityDirectory(StrictModel):
    """2026-08-08 用于保存当前 chunk 实体出现（单列表）"""

    entities: list[BoundEntity] = Field(default_factory=list)


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
    """2026-08-11 用于系统暂存 Agent 对活动案例的动作式解决结果"""

    case_id: str
    action: CaseAction
    type: CaseType = ""
    reason: str
    evidence_chunk_id: int = Field(ge=0)
    target_key: str
    target_ref: dict[str, Any] = Field(default_factory=dict)
    # dialogue 动作：改 dialogue_records
    speaker: str | None = None
    tone: str | None = None
    description: str | None = None
    is_inner_monologue: bool | None = None
    # fact 动作：建/改/删图关系（change_kind 表达变化）
    from_entity: str | None = None
    to_entity: str | None = None
    relation_type: str | None = None
    change_kind: str | None = None
    # foreshadowing 动作：改伏笔线程（setup_id 定位，字段即更新值）
    setup_summary: str | None = None
    setup_kind: str | None = None
    expected_payoff_family: str | None = None
    payoff_likelihood: str | None = None
    setup_status: str | None = None
    confidence: str | None = None
    strength: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> ResolvedCase:
        """2026-08-11 用于按 action 校验对应字段齐全且不混填"""
        if self.action == "dialogue":
            if self.speaker is not None:
                self.speaker = normalize_semantic_text(self.speaker, label="resolve.speaker")
            if self.tone is not None:
                self.tone = normalize_semantic_text(self.tone, label="resolve.tone")
            if self.description is not None:
                self.description = normalize_semantic_text(
                    self.description,
                    label="resolve.description",
                )
            if all(
                value is None
                for value in (self.speaker, self.tone, self.description, self.is_inner_monologue)
            ):
                raise ValueError("dialogue 动作必须至少提供 speaker/tone/description/is_inner_monologue 之一")
            return self
        if self.action == "fact":
            missing = [
                name
                for name in ("from_entity", "to_entity", "relation_type", "change_kind")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"fact 动作缺少字段: {missing}")
            self.from_entity = normalize_semantic_text(
                self.from_entity or "",
                label="resolve.from_entity",
            )
            self.to_entity = normalize_semantic_text(
                self.to_entity or "",
                label="resolve.to_entity",
            )
            return self
        if self.action == "foreshadowing":
            if all(
                value is None
                for value in (
                    self.setup_summary,
                    self.setup_kind,
                    self.expected_payoff_family,
                    self.payoff_likelihood,
                    self.setup_status,
                    self.confidence,
                    self.strength,
                )
            ):
                raise ValueError("foreshadowing 动作必须至少提供一个更新字段")
            for field_name in ("setup_summary", "expected_payoff_family"):
                value = getattr(self, field_name)
                if value is not None:
                    setattr(
                        self,
                        field_name,
                        normalize_semantic_text(value, label=f"resolve.{field_name}"),
                    )
            return self
        if self.action == "close":
            return self
        raise ValueError(f"未知案例动作: {self.action}")


class PendingCase(StrictModel):
    """2026-08-11 用于保存模型 push 登记的新连续性疑点案例"""

    type: CaseType
    chunk_id: int = Field(ge=0)
    keys: list[str] = Field(min_length=1)
    description: str
    target_key: str
    target_ref: dict[str, Any]
    evidence: EvidenceList


class AgentRunAudit(StrictModel):
    """2026-08-10 用于保存系统范围搜索凭据和领域修订记录（完整工具审计进入新审计表）"""

    allow_future_context: bool
    write_revisions: list[dict[str, Any]]
    rotation_case_ids: list[str]
    authorized_text_chunk_ids: list[int]
    closed_case_ids: list[str] = Field(default_factory=list)


class AgentRunResult(StrictModel):
    """2026-08-07 用于承载章节 Agent 完成后的正式系统结果"""

    run_id: str
    chapter_id: int = Field(gt=0)
    annotation: BoundChapterAnnotation
    resolved_cases: list[ResolvedCase]
    pushed_cases: list[PendingCase] = Field(default_factory=list)
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
    """2026-08-11 用于返回完成事务按 action 写入的解决目标（close 动作无目标）"""

    case_id: str
    action: CaseAction
    type: CaseType
    reason: str
    target_dialogue_id: str | None = None
    target_setup_id: str | None = None
    target_fact_id: str | None = None
    target_fact_revision: int | None = Field(default=None, gt=0)


class CompletionResult(StrictModel):
    """2026-08-07 用于回读或返回章节唯一完成事务"""

    annotation_id: str
    graph_version_id: str
    chapter_id: int = Field(gt=0)
    created_cases: list[CompletionCase] = Field(default_factory=list)
    resolved_cases: list[CompletionResolvedCase] = Field(default_factory=list)
