"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal, TypedDict

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """2026-08-07 用于统一拒绝标注合同中的额外字段"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


# 2026-08-30 事件参与者专属角色词不能写进同一参与者的人物功能字段
# （2026-09-11 见证者已并入 RoleFunction 词表，从拒绝表移除）
_EVENT_ONLY_ROLE_WORDS = frozenset({"地点", "行动者", "承受者", "协助者", "对抗者"})

# 2026-09-11 emotion 合同：五档整数分值 -2..2（模型直接输出数字，删除词表映射的解码回合）
EMOTION_SCORE_DESCRIPTION = (
    "情绪方向与强度分值，整数 -2..2"
    "（-2 强烈负面 / -1 轻微负面 / 0 中性 / 1 轻微正面 / 2 强烈正面）"
)


def coerce_emotion_score(value: object) -> int:
    """emotion 分值容错读取：合同值本就是 -2..2 整数，历史遗留/异常取值按中性 0 计"""
    if isinstance(value, int) and not isinstance(value, bool) and -2 <= value <= 2:
        return value
    return 0


# 2026-09-11 实体引用一律用运行期编号（write_entity 回执 n / search_graph 回执 n）；
# 名称是文本面的东西，进入写入合同前必须先换成编号，这里把"写名字"的失败直接转成可自纠报错
ENTITY_NUMBER_FIELD_HINT = "（编号取自 write_entity 回执 n 或 search_graph 回执 n；不接受实体名称）"


def _reject_entity_name_text(value: object) -> object:
    """2026-09-11 用于编号字段收到实体名称时给出直接可自纠的报错（纯数字字符串放行给 int 解析）"""
    if isinstance(value, str) and not value.strip().isdigit():
        raise ValueError(
            f"实体引用只接受编号（整数），收到名称 {value.strip()}："
            "请先 search_graph 按名称查询（新实体先 write_entity 登记），用回执编号引用"
        )
    return value


def entity_number_field_description(label: str) -> str:
    """2026-09-11 用于统一渲染编号字段描述（编号来源与禁令同一文案）"""
    return f"{label}{ENTITY_NUMBER_FIELD_HINT}"


# 2026-09-11 可复用的编号字段类型：写名称时在参数校验层给出可自纠报错，
# 供工具签名与 pydantic 模型共用（编号语义见 resolve_number）
EntityNumber = Annotated[int, BeforeValidator(_reject_entity_name_text)]


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
    """2026-08-07 用于约束人物在当前叙事动作中的功能

    2026-09-11 并入"见证者"：模型在 narrative_role 槽位写"见证者"的实测失败 10 次，
    旁观/见证类参与者确有人物功能语义，堵在枚举外只产生解码返工。
    """

    SUBJECT = "主体"
    OBJECT = "客体"
    SENDER = "发送者"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"
    WITNESS = "见证者"


class DialogueVerdict(StrEnum):
    """2026-08-11 用于约束对话候选的三态判断结果"""

    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    NOT_DIALOGUE = "not_dialogue"


class Tone(StrEnum):
    """对话语气的闭合取值域，没有贴合的用「其他」

    （2026-09-11 扩表：run e84339d1 实测 13 次 tone 失败全部是模型自造词，
    8 值词表与自然表达系统性错配；按实测高频词并入并加「其他」兜底。
    2026-09-14 本类以 enum 形态进入模型可见的工具 schema。）
    """

    CALM = "平静"
    ANGRY = "愤怒"
    SAD = "悲伤"
    JOYFUL = "喜悦"
    FEARFUL = "恐惧"
    TENSE = "紧张"
    SARCASTIC = "嘲讽"
    PLEADING = "恳求"
    SMUG = "得意"
    SURPRISED = "惊讶"
    CONFUSED = "疑惑"
    TIRED = "疲惫"
    RESIGNED = "无奈"
    DISTRESSED = "心疼"
    CONCERNED = "关切"
    DESPAIRING = "绝望"
    CURIOUS = "好奇"
    ADMIRING = "赞叹"
    PANICKED = "惊恐"
    ANXIOUS = "焦急"
    GREEDY = "贪婪"
    OTHER = "其他"


def tone_catalog_text() -> str:
    """2026-09-11 用于渲染 Agent 可见的语气闭合枚举全表（工具描述与报错同源）"""
    return "/".join(member.value for member in Tone)


# 2026-09-11 语气词整表：emotion 分值字段拒绝语气词时按本表给出纠错信息
_TONE_CHINESE_WORDS = frozenset(member.value for member in Tone)


# 2026-09-13 tone 严格口径：枚举外的值一律拒绝、不映射不放行；枚举含「其他」兜底，
# 没有贴合词时用它。run 431a66d8 实测 10 次 tone 拒绝（委屈/严厉/平和/调侃/温柔/激动）
# 全部是模型自然表达，被拒后逐条补写约多花 2 轮——这是闭合词表的既有代价，
# 拒绝回执必须给出全词表与「其他」指引，让模型一次就能自纠。
# 2026-09-14 写者侧 tone 恢复真 enum 参数（Tone | None）：闭合词表以 enum 进工具 schema，
# 模型看得到取值域（预防面），越界值由 schema 层拒绝、记录级转换器翻成
# record/field/code/expected 回执（含全词表与「其他」指引），与别的枚举参数同一条路径。
# 本函数只剩读者上报的载荷校验（reader.py，校验失败降级为警告）用得上。
def require_tone(value: object) -> Any:
    """语气闭合校验：只接受枚举内取值，枚举外一律拒绝并给出全词表与兜底指引"""
    if value is None or isinstance(value, Tone):
        return value
    text = str(value).strip()
    try:
        return Tone(text)
    except ValueError:
        pass
    raise ValueError(
        f"tone 必须是闭合语气枚举内的词：{text} 不在表内，"
        f"没有贴合的用「其他」。合法值: {tone_catalog_text()}"
    )


class EventParticipantRole(StrEnum):
    """2026-08-30 用于约束事件参与者角色并保留见证者与地点专属值"""

    SUBJECT = "主体"
    OBJECT = "客体"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"
    WITNESS = "见证者"
    LOCATION = "地点"


class RelationChangeKind(StrEnum):
    """2026-08-07 用于约束关系事实的生命周期变化（系统内部、持久化与 API 使用的英文值域）"""

    ASSERT = "assert"
    REINFORCE = "reinforce"
    WEAKEN = "weaken"
    BREAK = "break"
    REFINE = "refine"
    SUPERSEDE = "supersede"
    RETRACT = "retract"


class RelationChangeKindArg(StrEnum):
    """2026-09-11 模型面关系变化词（中文化）

    run e84339d1 实测模型把 assert 写成 create/add/建——英文闭集要求模型先解码再
    翻译；这里改成模型自然的汉语说法，工具层按 RELATION_CHANGE_KIND_LABELS 译回
    内部英文值，落库/API/前端契约零变化。
    """

    CREATE = "新增"
    REINFORCE = "强化"
    WEAKEN = "削弱"
    BREAK = "解除"
    REFINE = "修正"
    SUPERSEDE = "取代"
    RETRACT = "撤回"


RELATION_CHANGE_KIND_LABELS: dict[str, str] = {
    RelationChangeKindArg.CREATE.value: RelationChangeKind.ASSERT.value,
    RelationChangeKindArg.REINFORCE.value: RelationChangeKind.REINFORCE.value,
    RelationChangeKindArg.WEAKEN.value: RelationChangeKind.WEAKEN.value,
    RelationChangeKindArg.BREAK.value: RelationChangeKind.BREAK.value,
    RelationChangeKindArg.REFINE.value: RelationChangeKind.REFINE.value,
    RelationChangeKindArg.SUPERSEDE.value: RelationChangeKind.SUPERSEDE.value,
    RelationChangeKindArg.RETRACT.value: RelationChangeKind.RETRACT.value,
}


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

# 2026-08-19 事件树内部节点角色（一棵树 = 一个完整事件；根 = 触发该
# 事件的第一个自立动作；main = 主因链上；secondary = 父的兄弟即次因分支）
EventCauseRole = Literal["root", "main", "secondary"]

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


# 2026-09-13 实体标签约束单源：服务端校验、内部载荷 Field 描述、工具参数说明共用，
# 防止"约束只写在内部载荷模型上、模型可见的工具签名里没有"的两层模型漂移
# （run 1b388eb3 第 2 章实锤：模型写 6 字标签"情报头子之子"被拒，回执只报长度、
# 工具面上查不到该规则，模型原样重试后又放弃）
ENTITY_TAG_MAX_COUNT = 3
ENTITY_TAG_MAX_CHARS = 5
ENTITY_TAGS_RULE_TEXT = f"最多 {ENTITY_TAG_MAX_COUNT} 个，每个最多 {ENTITY_TAG_MAX_CHARS} 个字"


class EntityInput(StrictModel):
    """2026-08-08 用于提交当前 chunk 明确出现的实体"""

    name: str = Field(min_length=1, description="实体名称（新实体用本章出现的名称，已登记实体用登记名）")
    entity_type: EntityType = Field(
        description="实体大类：character=有生命的（含人/动物/灵兽/妖/器灵），item=无生命物品，"
        "location=地点，organization=组织；有生命就是 character，不要按戏份调整"
    )
    tags: list[str] = Field(
        default_factory=list,
        description=f'可空标签，{ENTITY_TAGS_RULE_TEXT}，如"灵兽""剑灵""法宝"',
    )
    description: str | None = Field(
        default=None,
        description="实体一句话简介（已登记实体不要重复提交）",
    )
    attributes: dict[str, JsonValue | None] | None = Field(
        default=None,
        description="JSON Merge Patch：普通值表示设置该属性，null 表示删除该属性；已登记实体只提交本次变化的字段",
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
        if len(normalized_tags) > ENTITY_TAG_MAX_COUNT:
            raise ValueError(f"entity.tags 最多 {ENTITY_TAG_MAX_COUNT} 个标签")
        if any(len(tag) > ENTITY_TAG_MAX_CHARS for tag in normalized_tags):
            raise ValueError(f"entity.tags 每个标签最多 {ENTITY_TAG_MAX_CHARS} 个字")
        self.tags = normalized_tags
        if self.description is not None:
            self.description = normalize_semantic_text(
                self.description,
                label="entity.description",
            )
        normalized_attributes: dict[str, JsonValue | None] = {}
        for key, value in (self.attributes or {}).items():
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
    emotional_valence: int = Field(ge=-2, le=2, description=EMOTION_SCORE_DESCRIPTION)
    narrative_function: NarrativeFunction
    pivot_moment: bool = False
    cliffhanger: bool = False

    @model_validator(mode="after")
    def normalize_summary(self) -> ChunkMetricsInput:
        """2026-08-07 用于规范化当前 chunk 摘要"""
        self.summary = normalize_semantic_text(self.summary, label="summary")
        return self


class DialogueInput(StrictModel):
    """2026-08-11 用于按候选序号提交对话三态判断"""

    candidate_index: int = Field(
        gt=0, description="候选序号，从 1 开始，与 DialogueCandidates 区块的 candidate_index 一致"
    )
    verdict: DialogueVerdict = Field(
        description="判断结果：dialogue=真实对话；inner_monologue=内心独白；"
        "not_dialogue=误判候选（如题字/描写被引号包裹）"
    )
    speaker: str | None = Field(
        default=None,
        description="说话人名称（已登记实体用登记名）；无法确认说话人时留 null",
    )
    # 2026-09-14 枚举字段本身即拒绝非法词，不再叠 require_tone（越界值由类型报错，
    # 全词表与「其他」指引由工具层记录级回执给出）
    tone: Tone | None = None

    @model_validator(mode="after")
    def validate_dialogue(self) -> DialogueInput:
        """2026-08-11 用于规范化说话人并约束三态字段组合"""
        if self.verdict == DialogueVerdict.NOT_DIALOGUE:
            if self.speaker is not None or self.tone is not None:
                raise ValueError("not_dialogue 候选只能提交 candidate_index 和 verdict；speaker/tone 必须为 null")
            return self
        if self.speaker is not None:
            self.speaker = normalize_semantic_text(
                self.speaker,
                label="dialogue.speaker",
            )
        return self


class EventParticipantInput(StrictModel):
    """2026-08-30 用于同时描述事件参与角色和人物动态状态（内部系统形态，实体=规范名）

    2026-09-13 小调用改造后只保留内部形态：模型面参与记录由
    write_character_participation / write_noncharacter_participation 逐条提交，
    服务端在领域结束时把编号翻成规范名并组装成本形态。
    """

    entity: str = Field(
        min_length=1,
        description="参与者实体名称，必须是图上已登记实体名（不是 name 字段）",
    )
    role: EventParticipantRole = Field(
        description="参与角色：主体/客体/接收者/帮助者/反对者/见证者/地点（地点作为参与者角色）"
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description="仅 character 参与者必填的人物叙事功能：主体/客体/发送者/接收者/帮助者/反对者/见证者",
    )
    action: str | None = Field(
        default=None,
        min_length=1,
        description="仅 character 参与者必填：一句话概括人物在本事件中的动作（不超过 15 字）",
    )
    emotion: int | None = Field(
        default=None,
        ge=-2,
        le=2,
        description=f"仅 character 参与者必填：动作伴随的情绪分值。{EMOTION_SCORE_DESCRIPTION}",
    )

    @field_validator("narrative_role", mode="before")
    @classmethod
    def _reject_event_role_words(cls, value: object) -> object:
        """2026-08-30 用于阻止事件专属角色词进入人物功能字段"""
        if isinstance(value, str) and value.strip() in _EVENT_ONLY_ROLE_WORDS:
            raise ValueError(
                "narrative_role 不接受 "
                f"{value.strip()}：地点、行动者等只用于事件参与者的 role 字段；"
                "人物功能使用 主体/客体/发送者/接收者/帮助者/反对者/见证者"
            )
        return value

    @field_validator("emotion", mode="before")
    @classmethod
    def _reject_tone_words_in_emotion(cls, value: object) -> object:
        """2026-08-30 用于阻止对话语气词进入人物情绪分值字段"""
        if isinstance(value, str) and value.strip() in _TONE_CHINESE_WORDS:
            raise ValueError(
                f"emotion 不接受 {value.strip()}：该字段是整数分值 -2..2"
                "（-2 强烈负面 … 2 强烈正面），语气词是对话 tone 字段的取值"
            )
        return value

    @model_validator(mode="after")
    def normalize_participant(self) -> EventParticipantInput:
        """2026-08-30 用于规范化参与者并约束人物动态字段成组提交"""
        self.entity = normalize_semantic_text(self.entity, label="event.participant.entity")
        if self.action is not None:
            self.action = normalize_semantic_text(self.action, label="event.participant.action")
        observation_fields = (self.narrative_role, self.action, self.emotion)
        if any(value is not None for value in observation_fields) and not all(
            value is not None for value in observation_fields
        ):
            raise ValueError("character 参与者的 narrative_role/action/emotion 必须同时提供或同时省略")
        return self


# 2026-08-18 事件森林/DAG 证据类型：统一非空列表，仅允许 GraphEvidence 或 TextEvidence
class TextEvidence(StrictModel):
    """2026-08-18 用于保存原文段落锚点证据（段落 ID + 字符范围）"""

    paragraph_ids: list[int] = Field(min_length=1, description="全局段落 ID 列表")
    char_start: int = Field(ge=0, description="锚点文本在章文本中的起始字符偏移")
    char_end: int = Field(gt=0, description="锚点文本在章文本中的结束字符偏移")

    @model_validator(mode="after")
    def validate_span(self) -> TextEvidence:
        """2026-08-18 用于保证文本证据段落和字符范围具有有效顺序"""
        if any(paragraph_id < 0 for paragraph_id in self.paragraph_ids):
            raise ValueError("TextEvidence.paragraph_ids 不能为负数")
        if self.char_end <= self.char_start:
            raise ValueError("TextEvidence.char_end 必须大于 char_start")
        if len(set(self.paragraph_ids)) != len(self.paragraph_ids):
            raise ValueError("TextEvidence.paragraph_ids 不允许重复")
        return self


class GraphEvidence(StrictModel):
    """2026-08-19 用于保存引用已有章节图事实的证据"""

    fact_id: str = Field(min_length=1)
    chapter_id: int = Field(gt=0)


EvidenceItem = Annotated[
    TextEvidence | GraphEvidence,
    Field(union_mode="left_to_right"),
]


class EventTreeHistoryResult(StrictModel):
    """2026-08-22search_event 暴露的历史事件树视图

    一棵树 = 一个完整事件；跨章树（大事件）通过 cause_tree_id 因果链跨越多章。
    """

    tree_id: str = Field(min_length=1)
    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    description: str = Field(min_length=1)
    participants: list[dict[str, Any]] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 2026-09-13 伏笔入森林：树根视图携带伏笔属性（发现活跃伏笔的检索通道）
    foreshadowing_status: str | None = None
    expected_payoff_family: str | None = None
    payoff_likelihood: str | None = None
    cross_chapter: bool = False
    root_node_id: str = Field(min_length=1, description="树根节点 id（落库 event_id）")
    edges: list[dict[str, Any]] = Field(default_factory=list)


@dataclass(slots=True)
class ChunkParagraphInfo:
    """2026-08-18 用于保存当前 chunk 内段落坐标映射（注入 prompt 标记和派生事件锚点）

    段落标记方案：prompt 在每个段落起始处注入 ¶N 标记（N 为 0 基 chunk 内序号）；
    Agent 提交 anchor_paragraph_ids 时使用这些 0 基序号，服务端按本映射校验并派生
    字符范围、文本哈希和 TextEvidence。
    """

    # 0 基 chunk 内序号 → 全局 paragraph_id
    paragraph_ids: list[int]
    # 0 基 chunk 内序号 → (start_char, end_char) 在 chunk 文本内的偏移
    char_spans: list[tuple[int, int]]
    # 0 基 chunk 内序号 → 段落文本
    texts: list[str]

    def __post_init__(self) -> None:
        """2026-08-18 用于校验三组列表长度一致且非空"""
        n = len(self.paragraph_ids)
        if n == 0:
            raise ValueError("ChunkParagraphInfo 不能为空")
        if len(self.char_spans) != n or len(self.texts) != n:
            raise ValueError("paragraph_ids / char_spans / texts 长度不一致")

    def is_valid_index(self, index: int) -> bool:
        """2026-08-18 用于校验段落序号在当前 chunk 范围内"""
        return 0 <= index < len(self.paragraph_ids)

    def char_span_for(self, indices: list[int]) -> tuple[int, int]:
        """2026-08-18 用于按段落序号列表派生合并字符范围"""
        if not indices or not all(self.is_valid_index(i) for i in indices):
            raise ValueError(f"无效段落序号: {indices}")
        starts = [self.char_spans[i][0] for i in indices]
        ends = [self.char_spans[i][1] for i in indices]
        return min(starts), max(ends)

    def text_for(self, indices: list[int]) -> str:
        """2026-08-18 用于按段落序号列表拼接段落文本"""
        if not indices or not all(self.is_valid_index(i) for i in indices):
            raise ValueError(f"无效段落序号: {indices}")
        return "".join(self.texts[i] for i in sorted(set(indices)))

    def global_paragraph_ids(self, indices: list[int]) -> list[int]:
        """2026-08-18 用于按段落序号列表返回全局 paragraph_id"""
        if not indices or not all(self.is_valid_index(i) for i in indices):
            raise ValueError(f"无效段落序号: {indices}")
        return [self.paragraph_ids[i] for i in sorted(set(indices))]


class RelationInput(StrictModel):
    """2026-08-12 用于通过实体名称提交本章确认存在的闭合类型关系边（内部系统形态）"""

    from_entity: str = Field(min_length=1, description="关系起点实体（图上的登记名称）")
    to_entity: str = Field(min_length=1, description="关系终点实体（图上的登记名称）")
    relation_type: RelationType = Field(description="闭合关系类型，方向与端点约束如下：\n" + relation_catalog_text())

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
        if self.from_entity == self.to_entity and self.relation_type != RelationType.SAME_CHARACTER:
            raise ValueError("关系两端不能是同一名称")
        return self


class DialogueCandidate(StrictModel):
    """2026-08-07 用于系统保存对话候选真实原文和位置"""

    candidate_key: str = Field(min_length=1)
    # 2026-08-14 M7：允许负 chunk_id（子块运行时 ID，§20），候选不落库
    chunk_id: int
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


class BoundCharacterObservation(StrictModel):
    """2026-08-30 用于保存从事件人物参与者派生的动态状态"""

    character: str = Field(min_length=1)
    role_function: RoleFunction
    action: str = Field(min_length=1)
    emotion: int = Field(ge=-2, le=2)


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


class BoundEvent(StrictModel):
    """2026-08-22事件树节点（服务端派生角色、id；章级证据由持久化层盖章）

    节点由 write_event 服务端生成：node_id 即最终落库 event_id，
    因果边仅允许 root 携带跨章前驱（cause_tree_id 的根节点），环构造性不可能。
    2026-08-22 重构：证据升为章级单份，节点不再携带锚点/字符区间/哈希/证据。
    """

    node_id: str = Field(min_length=1, description="服务端派生的节点 id（=落库 event_id）")
    tree_id: str = Field(min_length=1)
    parent_node_id: str | None = Field(default=None, description="root 为 None")
    cause_role: EventCauseRole
    description: str = Field(min_length=1)
    participants: list[EventParticipantInput] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 2026-09-13 伏笔入森林：根事件携带伏笔属性（落库到 event_nodes 根列）
    expected_payoff_family: str | None = None
    payoff_likelihood: PayoffLikelihood | None = None
    # 仅跨章树的根节点携带 [cause_tree_id 根节点 id]，其余恒为空
    causal_event_refs: list[str] = Field(default_factory=list)


class BoundRelation(RelationInput):
    """2026-08-07 用于系统注入关系方向和语义元数据"""

    directionality: Directionality
    relation_semantics: RelationSemantics


class SentenceLabelInput(StrictModel):
    """2026-09-07 用于提交 agent 自选句子的句级情绪标签（句级监督信号）

    2026-09-13 小调用改造：从 write_metrics 的可选列表参数拆成 write_sentence_label
    逐句提交（一次一个完整语义单元），绑定与去重语义不变。
    """

    sentence: str = Field(
        min_length=2,
        max_length=2000,
        description="从当前章节正文原样摘录的完整句子（系统按原文定位绑定）",
    )
    emotion: int = Field(ge=-2, le=2, description=f"整句情绪分值。{EMOTION_SCORE_DESCRIPTION}")

    @model_validator(mode="after")
    def normalize_sentence(self) -> SentenceLabelInput:
        """2026-09-07 用于规范化自选句原文"""
        self.sentence = normalize_semantic_text(self.sentence, label="sentence_label.sentence")
        return self


class BoundSentenceLabel(StrictModel):
    """2026-09-07 用于保存系统定位绑定后的自选句情绪标签（章文本内字符区间）"""

    sentence: str = Field(min_length=1)
    emotion: int
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self) -> BoundSentenceLabel:
        """2026-09-07 用于保证句区间有效且与原文一致"""
        if self.end <= self.start:
            raise ValueError("BoundSentenceLabel end 必须大于 start")
        return self


class BoundChunkAnnotation(StrictModel):
    """2026-08-07 用于保存系统完成绑定的单个 chunk 正式标注

    2026-09-04 单一写面：图域（entities/relations）不再是本模型的字段——
    实体与关系的运行时真相源是 FactGraph，持久化从其操作日志
    （entity_ops / relation_assert_ops / relation_change_ops）派生。
    resolve_fact_case 只更新 FactGraph，resolved_cases 不再承载 fact 动作。

    2026-09-07 句级监督：agent 自选句情绪标签随本模型落库；默认空列表保持
    旧 run payload 反序列化兼容（fetch_chapter_annotations_full 会重校验）。
    """

    # 2026-08-14 M7：允许负 chunk_id（子块运行时 ID，§20）；落库前由 workflow 合并为真实 chunk
    chunk_id: int
    metrics: ChunkMetricsInput
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    # 2026-09-07 句级监督：agent 自选句情绪标签（随 write_metrics 的 sentence_labels
    # 可选参数搭车提交，服务端定位绑定，不设独立工具）
    sentence_labels: list[BoundSentenceLabel] = Field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（如候选>0但载荷为空），仅留痕不阻断
    coverage_warnings: list[str] = Field(default_factory=list)


class BoundChapterAnnotation(StrictModel):
    """2026-08-07 用于保存最新语义写入合同的章节正式标注"""

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
    """2026-08-30 用于查询服务返回配置范围内的原文命中与精确授权段落"""

    chapter_id: int = Field(gt=0)
    paragraph_ids: list[int] = Field(min_length=1)
    content: str = Field(min_length=1)
    keyword_score: float = Field(ge=0)
    semantic_score: float | None = None

    @model_validator(mode="after")
    def validate_paragraph_ids(self) -> TextSearchResult:
        """2026-08-30 用于校验命中段落身份非负且不重复"""
        if any(paragraph_id < 0 for paragraph_id in self.paragraph_ids):
            raise ValueError("TextSearchResult.paragraph_ids 不能为负数")
        if len(set(self.paragraph_ids)) != len(self.paragraph_ids):
            raise ValueError("TextSearchResult.paragraph_ids 不允许重复")
        return self


class CaseSearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回活动连续性案例

    2026-09-11 案例改检索制：created_chapter 供模型判断案例新旧
    （池内时间轴只剩章节序号）。
    """

    id: str = Field(min_length=1)
    type: CaseType
    chunk_id: int = Field(ge=0)
    created_chapter: int = Field(default=0, ge=0)
    keys: list[str] = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=100)
    state: Literal["active"] = "active"


class ActiveCaseDetails(CaseSearchResult):
    """2026-08-07 用于系统内部携带案例稳定目标"""

    target_key: str = Field(min_length=1)
    target_ref: dict[str, Any]


SearchResultItem = CaseSearchResult


class CasePoolSummary(StrictModel):
    """2026-09-11 用于在案例池检索回执中汇报可检索规模（案例本体不再随正文注入）

    active_total/by_type 只统计未被本轮隐藏（未解决）的 active 案例，
    即模型此刻用 search_pool 还能检索到的条目。
    """

    active_total: int = Field(default=0, ge=0)
    by_type: dict[str, int] = Field(default_factory=dict)


class SearchResult(StrictModel):
    """2026-08-07 用于查询服务内部返回案例结果

    2026-09-11 案例改检索制：pool 汇报池内剩余规模与类型分布，truncated 表示
    命中超过 limit 只返回了前 limit 条。
    """

    results: list[SearchResultItem] = Field(default_factory=list, max_length=50)
    pool: CasePoolSummary = Field(default_factory=CasePoolSummary)
    truncated: bool = False


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
    # 2026-09-13 伏笔入森林：把本章事件挂进伏笔树（foreshadowing 边），可选更新根属性
    foreshadowing_action: Literal["reinforce", "payoff"] | None = None
    foreshadowing_root_event_id: str | None = None
    foreshadowing_event_id: str | None = None
    expected_payoff_family: str | None = None
    payoff_likelihood: str | None = None
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
            if all(value is None for value in (self.speaker, self.tone, self.description, self.is_inner_monologue)):
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
            missing = [
                name
                for name in ("foreshadowing_action", "foreshadowing_root_event_id", "foreshadowing_event_id")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"foreshadowing 动作缺少字段: {missing}")
            if self.expected_payoff_family is not None:
                self.expected_payoff_family = normalize_semantic_text(
                    self.expected_payoff_family,
                    label="resolve.expected_payoff_family",
                )
            # 2026-08-16 P3：枚举字段不再降级为 "unknown"，非法值直接拦截入库
            for field_name, valid_values in (
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
                    raise ValueError(f"resolve.{field_name} 枚举漂移: {value!r}，合法值: {sorted(valid_values)}")
            return self
        if self.action == "close":
            return self
        raise ValueError(f"未知案例动作: {self.action}")


class PendingCase(StrictModel):
    """2026-08-11 用于保存模型 push 登记的新连续性疑点案例"""

    type: CaseType
    # 2026-08-14 M7：允许负 chunk_id（子块运行时 ID，§20）；落库前由 workflow 映射回真实 chunk
    chunk_id: int
    keys: list[str] = Field(min_length=1)
    description: str = Field(min_length=1, max_length=100)
    target_key: str
    target_ref: dict[str, Any]


class AgentRunAudit(StrictModel):
    """2026-08-19 用于保存系统范围搜索凭据和领域写入记录（完整工具审计进入新审计表）

    2026-08-30：文本检索返回正文时即时登记精确段落授权；sub_chunk_index 记录子块协议运行序号。
    """

    allow_future_context: bool
    write_records: list[dict[str, Any]]
    authorized_chapter_ids: list[int]
    authorized_text_paragraph_ids: list[int]
    # 2026-08-18 P2：历史事件只能使用本轮 search_event_history 返回的稳定 ID
    authorized_event_ids: list[str] = Field(default_factory=list)
    closed_case_ids: list[str] = Field(default_factory=list)
    sub_chunk_index: int = 0


class AgentRunResult(StrictModel):
    """2026-08-07 用于承载章节 Agent 完成后的正式系统结果

    2026-09-04 单一写面：图域（实体/关系/案例关系变更）的运行时真相源是 FactGraph，
    本结果携带子块 drain 出的三份操作日志，持久化据此派生实体行、关系 assert 事实与
    案例关系变更事实；resolved_cases 只保留非图裁决（dialogue/foreshadowing/close）。
    """

    run_id: str
    chapter_id: int = Field(gt=0)
    annotation: BoundChapterAnnotation
    resolved_cases: list[ResolvedCase]
    pushed_cases: list[PendingCase] = Field(default_factory=list)
    entity_ops: list[dict[str, Any]] = Field(default_factory=list)
    relation_assert_ops: list[dict[str, Any]] = Field(default_factory=list)
    relation_change_ops: list[dict[str, Any]] = Field(default_factory=list)
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
    target_fact_id: str | None = None
    # 2026-09-13 伏笔入森林：解决目标是伏笔树根与挂进树的事件
    target_root_event_id: str | None = None
    target_event_id: str | None = None


class CompletionResult(StrictModel):
    """2026-08-07 用于回读或返回章节唯一完成事务"""

    annotation_id: str
    chapter_id: int = Field(gt=0)
    created_cases: list[CompletionCase] = Field(default_factory=list)
    resolved_cases: list[CompletionResolvedCase] = Field(default_factory=list)
