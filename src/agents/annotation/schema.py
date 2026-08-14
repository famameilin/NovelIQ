"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """2026-08-07 用于统一拒绝标注合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# 2026-08-12 事件参与者专属角色词：模型常误写进人物观察的 role_function
_EVENT_ONLY_ROLE_WORDS = frozenset({"见证者", "地点", "行动者", "承受者", "协助者", "对抗者"})

# 2026-08-12 对话 tone 中文枚举：模型常误写进 emotional_valence（该字段是英文枚举）
_TONE_CHINESE_WORDS = frozenset({"平静", "愤怒", "悲伤", "喜悦", "恐惧", "紧张", "嘲讽", "恳求"})


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
    """2026-08-07 用于约束伏笔置信度（Agent 可见合同仅伏笔使用）"""

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


class DialogueVerdict(StrEnum):
    """2026-08-11 用于约束对话候选的三态判断结果"""

    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    NOT_DIALOGUE = "not_dialogue"


class Tone(StrEnum):
    """2026-08-11 用于约束对话语气的闭合枚举"""

    CALM = "平静"
    ANGRY = "愤怒"
    SAD = "悲伤"
    JOYFUL = "喜悦"
    FEARFUL = "恐惧"
    TENSE = "紧张"
    SARCASTIC = "嘲讽"
    PLEADING = "恳求"


class EventParticipantRole(StrEnum):
    """2026-08-12 用于约束事件参与者的闭合角色（与人物观察共用格雷马斯词表；地点作为参与者角色，不单独设字段）"""

    SUBJECT = "主体"
    OBJECT = "客体"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"
    WITNESS = "见证者"
    LOCATION = "地点"


class RelationChangeKind(StrEnum):
    """2026-08-07 用于约束关系事实的生命周期变化（系统内部与案例解决使用）"""

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
    LEADER = "领导"


class SetupKind(StrEnum):
    """2026-08-07 用于约束伏笔 setup 的宽口径类别（系统内部默认值使用）"""

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
    """2026-08-07 用于约束伏笔线程当前阶段（系统内部默认值使用）"""

    OPEN = "open"
    REINFORCED = "reinforced"
    LIKELY_PAID_OFF = "likely_paid_off"


class PayoffLikelihood(StrEnum):
    """2026-08-07 用于约束伏笔回收可能性（系统内部默认值使用）"""

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
_POSITIONED_ENTITY_TYPES: tuple[EntityType, ...] = (
    "character",
    "item",
    "organization",
    "location",
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
    "领导": {
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
        "from_types": _POSITIONED_ENTITY_TYPES,
        "to_types": _LOCATION_ENTITY_TYPES,
    },
}


_DIRECTION_LABEL: dict[str, str] = {"directed": "单向", "bidirectional": "双向"}


def relation_catalog_text() -> str:
    """2026-08-11 用于渲染 Agent 可见的闭合关系目录（方向/语义/端点类型）"""
    lines: list[str] = []
    for relation_type, definition in RELATION_DEFINITIONS.items():
        direction = _DIRECTION_LABEL[definition["directionality"]]
        semantics = "同一人物归并" if definition["semantics"] == "same_character" else "普通关系"
        from_types = "/".join(definition["from_types"])
        to_types = "/".join(definition["to_types"])
        lines.append(f"{relation_type}：{direction}，{from_types} → {to_types}，{semantics}")
    return "\n".join(lines)


def normalize_semantic_text(value: str, *, label: str) -> str:
    """2026-08-07 用于统一规范化 Agent 提交的人类可读文本"""
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError(f"{label} 不能为空")
    return normalized


class EntityInput(StrictModel):
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
    attributes: dict[str, JsonValue | None] = Field(
        default_factory=dict,
        description="JSON Merge Patch：普通值表示设置该属性，null 表示删除该属性；"
        "已登记实体只提交本次变化的字段",
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
        normalized_attributes: dict[str, JsonValue | None] = {}
        for key, value in self.attributes.items():
            cleaned = unicodedata.normalize("NFC", key).strip()
            if not cleaned:
                raise ValueError("entity.attributes 键不能为空")
            normalized_attributes[cleaned] = value
        self.attributes = normalized_attributes
        return self


class EntityDirectoryInput(StrictModel):
    """2026-08-08 用于提交当前 chunk 出现的全部实体（单列表）"""

    entities: list[EntityInput] = Field(default_factory=list)


class ChunkMetricsInput(StrictModel):
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


class CharacterObservationInput(StrictModel):
    """2026-08-07 用于提交人物在当前 chunk 的动作和功能"""

    character: str = Field(min_length=1, description="人物名称（已登记实体用登记名）")
    role_function: RoleFunction = Field(description="人物在本动作中的功能角色：主体/客体/发送者/接收者/帮助者/反对者")
    action: str = Field(min_length=1, description="动作描述，一句话概括人物做了什么")
    emotion: EmotionalValence = Field(description="动作伴随的情绪方向与强度（英文枚举）")

    @field_validator("role_function", mode="before")
    @classmethod
    def _reject_event_role_words(cls, value: object) -> object:
        """2026-08-12 用于给事件角色词写进 role_function 的错误附加纠正引导"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "role_function 不接受 "
                f"{value.strip()}：见证者、地点等只用于事件参与者的 role 字段；"
                "人物观察 role_function 使用 主体/客体/发送者/接收者/帮助者/反对者"
            )
        return value

    @field_validator("emotion", mode="before")
    @classmethod
    def _reject_tone_words_in_emotion(cls, value: object) -> object:
        """2026-08-12 用于给 tone 中文词写进 emotional_valence 的错误附加纠正引导"""
        if isinstance(value, str) and value.strip() in _TONE_CHINESE_WORDS:
            raise ValueError(
                f"emotional_valence 不接受 {value.strip()}：该字段使用英文枚举"
                "（strong_positive/mild_positive/neutral/mild_negative/strong_negative），"
                "中文枚举（平静/愤怒/喜悦等）是对话 tone 字段的取值"
            )
        return value

    @model_validator(mode="after")
    def normalize_character_observation(self) -> CharacterObservationInput:
        """2026-08-07 用于规范化人物名称和动作说明"""
        self.character = normalize_semantic_text(self.character, label="character")
        self.action = normalize_semantic_text(self.action, label="action")
        return self


class DialogueInput(StrictModel):
    """2026-08-11 用于按候选序号提交对话三态判断"""

    candidate_index: int = Field(gt=0, description="候选序号，从 1 开始，与系统候选列表的 index 一致")
    verdict: DialogueVerdict = Field(
        description="判断结果：dialogue=真实对话；inner_monologue=内心独白；"
        "not_dialogue=误判候选（如题字/描写被引号包裹）"
    )
    speaker: str | None = Field(
        default=None,
        description="说话人名称（已登记实体用登记名）；无法确认说话人时留 null",
    )
    tone: Tone | None = Field(default=None, description="对话语气闭合枚举：平静/愤怒/悲伤/喜悦/恐惧/紧张/嘲讽/恳求")

    @model_validator(mode="after")
    def validate_dialogue(self) -> DialogueInput:
        """2026-08-11 用于规范化说话人并约束三态字段组合"""
        if self.verdict == DialogueVerdict.NOT_DIALOGUE:
            if self.speaker is not None or self.tone is not None:
                raise ValueError(
                    "not_dialogue 候选只能提交 candidate_index 和 verdict；speaker/tone 必须为 null"
                )
            return self
        if self.speaker is not None:
            self.speaker = normalize_semantic_text(
                self.speaker,
                label="dialogue.speaker",
            )
        return self


# 2026-08-12 数组格式对话提交：位置 [candidate_index, verdict, speaker, tone]，
# speaker/tone 未知时 null；比对象格式省去字段名 token，且未提交候选默认 not_dialogue
DialogueSubmissionItem = tuple[int, DialogueVerdict, str | None, Tone | None]


class EventParticipantInput(StrictModel):
    """2026-08-11 用于描述实体在当前事件中的闭合角色"""

    entity: str = Field(min_length=1)
    role: EventParticipantRole = Field(
        description="参与角色：主体/客体/接收者/帮助者/反对者/见证者/地点（地点作为参与者角色）"
    )

    @model_validator(mode="after")
    def normalize_participant(self) -> EventParticipantInput:
        """2026-08-11 用于规范化参与实体名称"""
        self.entity = normalize_semantic_text(self.entity, label="event.participant.entity")
        return self


class EventInput(StrictModel):
    """2026-08-11 用于提交不依赖任意 event_type 的事件描述和参与者角色"""

    description: str = Field(min_length=1)
    participants: list[EventParticipantInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_event(self) -> EventInput:
        """2026-08-11 用于规范化事件说明"""
        self.description = normalize_semantic_text(
            self.description,
            label="event.description",
        )
        return self


class RelationInput(StrictModel):
    """2026-08-12 用于通过实体名称提交本章确认存在的闭合类型关系边"""

    from_entity: str = Field(min_length=1, description="关系起点实体（图上的登记名称）")
    to_entity: str = Field(min_length=1, description="关系终点实体（图上的登记名称）")
    relation_type: RelationType = Field(
        description="闭合关系类型，方向与端点约束如下：\n" + relation_catalog_text()
    )

    @model_validator(mode="after")
    def normalize_relation(self) -> RelationInput:
        """2026-08-11 用于规范化关系两端实体名称"""
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


class ForeshadowingInput(StrictModel):
    """2026-08-11 用于提交新伏笔描述与置信度（只创建新伏笔）"""

    description: str = Field(min_length=1, description="伏笔描述，一句话说明埋设了什么悬念")
    confidence: Confidence = Field(description="本次判断的置信度：high/medium/low")

    @model_validator(mode="after")
    def normalize_foreshadowing(self) -> ForeshadowingInput:
        """2026-08-11 用于规范化伏笔描述"""
        self.description = normalize_semantic_text(
            self.description,
            label="foreshadowing.description",
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


class BoundEntity(EntityInput):
    """2026-08-11 用于系统绑定当前 chunk 实体出现（与输入模型同构，标记已校验）"""


class BoundEntityDirectory(StrictModel):
    """2026-08-08 用于保存当前 chunk 实体出现（单列表）"""

    entities: list[BoundEntity] = Field(default_factory=list)


class BoundCharacterObservation(CharacterObservationInput):
    """2026-08-11 用于系统绑定人物观察（与输入模型同构，标记已校验）"""


class BoundDialogue(StrictModel):
    """2026-08-11 用于系统绑定有效对话原文位置和语义结果"""

    candidate_index: int = Field(gt=0)
    candidate_key: str
    content: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    speaker: str | None = None
    tone: Tone | None = None
    is_inner_monologue: bool = False


class BoundEvent(EventInput):
    """2026-08-11 用于系统绑定事件（与输入模型同构，标记已校验）"""


class BoundRelation(RelationInput):
    """2026-08-07 用于系统注入关系方向和语义元数据"""

    directionality: Directionality
    relation_semantics: RelationSemantics


class BoundForeshadowing(ForeshadowingInput):
    """2026-08-11 用于系统绑定伏笔（与输入模型同构，标记已校验）"""


class BoundChunkAnnotation(StrictModel):
    """2026-08-07 用于保存系统完成绑定的单个 chunk 正式标注"""

    chunk_id: int = Field(ge=0)
    metrics: ChunkMetricsInput
    entities: BoundEntityDirectory
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    relations: list[BoundRelation]
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
    state: Literal["active"] = "active"


class ActiveCaseDetails(CaseSearchResult):
    """2026-08-07 用于系统内部携带案例稳定目标"""

    target_key: str = Field(min_length=1)
    target_ref: dict[str, Any]


class ForeshadowingSearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回伏笔线程"""

    record_id: str
    content: dict[str, Any]


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
    target_key: str
    target_ref: dict[str, Any] = Field(default_factory=dict)
    # dialogue 动作：改 dialogue_records
    speaker: str | None = None
    tone: Tone | None = None
    description: str | None = None
    is_inner_monologue: bool | None = None
    # fact 动作：建/改/删图关系（change_kind 表达变化）
    from_entity: str | None = None
    to_entity: str | None = None
    relation_type: str | None = None
    change_kind: RelationChangeKind | None = None
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
                self.tone = Tone(normalize_semantic_text(self.tone, label="resolve.tone"))
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
            # 2026-08-13 P1-2：枚举字段非法值降级为 "unknown" 而非报错，
            # 避免诊断阶段 calculate_foreshadow_expectation 用常量字典索引直接 KeyError。
            # 合法键集合与 repository.py 的 _EXPECTATION_* 字典一致
            # （test_expectation_mappings_cover_enum_domains 已锁定该对应关系）。
            for field_name, valid_values in (
                (
                    "setup_status",
                    {status.value for status in SetupStatus},
                ),
                (
                    "payoff_likelihood",
                    {likelihood.value for likelihood in PayoffLikelihood},
                ),
                (
                    "strength",
                    {confidence.value for confidence in Confidence},
                ),
            ):
                value = getattr(self, field_name)
                if value is not None and value not in valid_values:
                    setattr(self, field_name, "unknown")
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
