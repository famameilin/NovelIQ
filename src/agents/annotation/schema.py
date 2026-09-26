"""
章节标注 Agent 语义写入合同与系统绑定模型
"""

# 2026-09-17 模型可见文案约定：本模块的类 docstring 会被 pydantic 渲染成字段的
# JSON schema 说明、直接进模型可见面（工具参数 schema、程序面 API 目录都是这份），
# 所以 docstring 一律按"说明"写——这是什么字段、能取哪些值、怎么判；开发史、
# 裁决过程、实测数字写成类上方的 # 注释，不进模型面。

from __future__ import annotations

import re
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

# 2026-09-18 pivot/cliffhanger 说明单源：写者面 write_metrics 签名、ChapterMetricsInput
# 与 subagent 面 metric 构造器目录共用同一份文本（只陈述字段机制，不裁断与 narrative_function 的分工）
# 2026-09-18 说明改为判据口径：原句把"全书按 pivot_moment=true 的章数÷有效章数算
# chapter_pivot_rate"这类聚合公式写给模型，模型据此判不了任何一段正文；聚合口径属指标文档
# （src/config/constants/metrics_contracts.py 的 chapter_pivot_rate 条目）。
PIVOT_MOMENT_DESCRIPTION = (
    "本章是否标记为叙事转折点（布尔，独立字段）。narrative_function 说的是本章自身的叙事功能，"
    "本字段说的是本章是否构成转折点，两者各自判断、允许不一致。"
)
CLIFFHANGER_DESCRIPTION = "本章是否以悬念收尾（布尔，追读钩子）。"


def coerce_emotion_score(value: object) -> int:
    """emotion 分值容错读取：合同值本就是 -2..2 整数，历史遗留/异常取值按中性 0 计"""
    if isinstance(value, int) and not isinstance(value, bool) and -2 <= value <= 2:
        return value
    return 0


# 2026-09-19 id 纪律：实体引用 = run 级 uuid id 或本 章内 write_entity 自定的 el 键。
# el 由模型指定、登记即绑定（同回合后面的调用直接可用，不等回执）；id 由服务端确定性铸造、
# 回执与检索视图同值；名称仍是非法引用，在账本解析点按 unknown_el / unknown_entity_id 拒绝。
ENTITY_REF_FIELD_HINT = (
    "（字符串=write_entity / search_graph 回执里的 run 级 id；"
    "或本章 write_entity 自定的 el 键；不接受实体名称）"
)


def _reject_blank_entity_ref(value: object) -> object:
    """用于拒绝空引用；字符串按 el 键或 run 级 id 进入账本解析"""
    if isinstance(value, str) and not value.strip():
        raise ValueError("实体引用不能为空")
    return value


def entity_ref_field_description(label: str) -> str:
    """2026-09-14 用于统一渲染实体引用字段描述（两种键空间与禁令同一文案）"""
    return f"{label}{ENTITY_REF_FIELD_HINT}"


class EntityRefType:
    """2026-09-20 用于把"实体引用"这一注解标记出来

    程序面目录渲染按标记给类型标签（"实体引用"），否则 from_entity 这种字段在签名里
    只能照底层类型写"文本"——引用写什么正是被拒最多的那一族（run 54a72932：写者面
    295 次 write_relation 失败里 135 次填的是实体名称）。注解元数据本身不参与校验。
    """


# 可复用的实体引用类型：供工具签名与参与者数组模型共用（解析见 ledger.resolve_entity_ref）
EntityRef = Annotated[str, BeforeValidator(_reject_blank_entity_ref), EntityRefType()]


def _reject_text_evidence(value: object) -> object:
    """2026-09-20 用于把段落编号类参数收成整数

    证据一律是"段首可见号"（整数），不是引文、不是实体名：run 54a72932 里模型在
    write_relation 的新增分支填引文（"伯安他爹铁帅"），整笔写入按 schema 校验失败作废
    160 次，而该字段在新增分支本来不被消费。数字字符串按原意接受，其余当场拒。
    """
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValueError(f"只能是段落开头的段首号（整数，如 12），不能是引文或名称：{value!r}")


# 段落编号参数（关系变更的 evidence）：可空，收整数；同形的段落号参数见各构造器的 evidence
EvidenceNumber = Annotated[int | None, BeforeValidator(_reject_text_evidence)]


class NarrativeFunction(StrEnum):
    """本章在叙事结构中的功能，只能取一个

    冲突=已展开的矛盾在本章有一次正面交锋；铺垫=本章埋下后文要用的条件、线索或关系；
    转折=本章改变了人物的处境、立场或认知。按本章最主要的作用判。
    """

    CONFLICT = "冲突"
    SETUP = "铺垫"
    TURNING_POINT = "转折"


# 2026-09-14 写入面重构：本枚举取代旧 PayoffLikelihood，成为伏笔唯一的可能性词表——
# 根事件的 confidence 与伏笔树根的 strength 共用同一取值域
# （落库列名 payoff_likelihood 不变，值域从二值扩为三档）。
class Confidence(StrEnum):
    """伏笔的可能性档位

    high=正文有明确指向该伏笔的表述；medium=有较明显的暗示但没有点明；
    low=只是可疑的苗头，是否成立取决于后文。
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# 2026-09-11 并入"见证者"：模型在 narrative_role 槽位写"见证者"的实测失败 10 次，
# 旁观/见证类参与者确有人物功能语义，堵在枚举外只产生解码返工。
class RoleFunction(StrEnum):
    """人物在当前叙事动作里承担的功能

    主体=发起动作的人；客体=动作的承受者；发送者/接收者=信息传递的两端；
    帮助者=协助主体的第三方；反对者=阻碍主体的第三方；见证者=在场但没有介入的人。
    按这个动作里的作用判，不按全章戏份判。
    """

    SUBJECT = "主体"
    OBJECT = "客体"
    SENDER = "发送者"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"
    WITNESS = "见证者"


class DialogueVerdict(StrEnum):
    """对话候选的三态判定

    dialogue=人物之间真的说出口的话；inner_monologue=人物心里的想法（含未被他人听见的自语）；
    not_dialogue=被引号包住但不是人物说话（引文、书名、术语强调等）。
    """

    DIALOGUE = "dialogue"
    INNER_MONOLOGUE = "inner_monologue"
    NOT_DIALOGUE = "not_dialogue"


# 2026-09-11 扩表：run e84339d1 实测 13 次 tone 失败全部是模型自造词，8 值词表与自然表达
# 系统性错配；按实测高频词并入并加「其他」兜底。
# 2026-09-14 二次扩表：恭敬×4（师徒/拜谒高频，22 值无敬档）、戏谑/调侃（嘲讽只覆盖贬义讥讽、
# 缺亲昵玩笑反差档）为真词表缺口；其余拒词（苦涩/痛苦/低沉→悲伤、无赖/憨厚→人设非语气、
# 坚定/郑重→平静）归既有词或「其他」，不并入以免词表通胀。
class Tone(StrEnum):
    """说话人当下的语气，闭合词表，没有贴合的用「其他」

    按说话方式与当下情绪判，不按人物性格或听话人的感受判；只能取本表的值。
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
    DEFERENTIAL = "恭敬"
    TEASING = "戏谑"
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


class EventParticipantRole(StrEnum):
    """参与实体在这次事件里的角色

    主体=事件的发起者；客体=事件的承受者；接收者=接收对象；帮助者=协助主体的人；
    反对者=阻碍事件的人；见证者=在场但未介入的人；地点=事件发生的场所（只给 location 实体用）。
    """

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


# 2026-09-11 中文化：run e84339d1 实测模型把 assert 写成 create/add/建——英文闭集要求
# 模型先解码再翻译。这里改成模型自然的汉语说法，工具层按 RELATION_CHANGE_KIND_LABELS
# 译回内部英文值，落库/API/前端契约零变化。
class RelationChangeKindArg(StrEnum):
    """本章对某条已登记关系做了什么变化

    新增=确认这条关系存在；强化=关系更紧密；削弱=关系变疏远或分量下降；
    解除=关系终止；修正=关系的性质或描述被更正；取代=被另一条关系替换；
    撤回=此前登记有误、撤销该条。
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
    """两张实体之间成立的关系类型，闭合词表

    只能取本表的值；每个取值的语义与两端实体类型约束写在 relation_type 字段说明里。
    「同一人物」专用于同一个人换了写法或身份，不是普通关系。
    """

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


class EntityType(StrEnum):
    """实体大类

    character=有生命的（含人/动物/灵兽/妖/器灵），item=无生命物品，
    location=地点，organization=组织；有生命就是 character，不要按戏份调整。
    """

    CHARACTER = "character"
    LOCATION = "location"
    ITEM = "item"
    ORGANIZATION = "organization"


class EventChildType(StrEnum):
    """子事件在树内的位置

    main=顺延主因链（成为新的链尾）；secondary=挂在当时主链尾（次因分支）。
    """

    MAIN = "main"
    SECONDARY = "secondary"


Directionality = Literal["directed", "bidirectional"]
RelationSemantics = Literal["ordinary", "same_character"]
CaseType = str
CaseAction = Literal["dialogue", "fact", "foreshadowing", "close", "promise"]
CaseState = Literal["active", "resolved"]
DialogueParseStatus = Literal["paired_quote", "dialogue_line", "unclosed_quote"]

# 2026-08-19 事件树内部节点角色（一棵树 = 一个完整事件；根 = 触发该
# 事件的第一个自立动作；main = 主因链上；secondary = 父的兄弟即次因分支）
# 2026-09-14 模型面 type 参数用 EventChildType（root 由 isroot=true 表达，不外露）
EventCauseRole = Literal["root", "main", "secondary"]

_ACTOR_ENTITY_TYPES: tuple[EntityType, ...] = (EntityType.CHARACTER, EntityType.ORGANIZATION)
_CHARACTER_ENTITY_TYPES: tuple[EntityType, ...] = (EntityType.CHARACTER,)
_ORGANIZATION_ENTITY_TYPES: tuple[EntityType, ...] = (EntityType.ORGANIZATION,)
_LOCATION_ENTITY_TYPES: tuple[EntityType, ...] = (EntityType.LOCATION,)
_POSITIONED_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType.CHARACTER,
    EntityType.ITEM,
    EntityType.ORGANIZATION,
    EntityType.LOCATION,
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
        "to_types": _ORGANIZATION_ENTITY_TYPES,
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
    """2026-08-08 用于提交当前章 明确出现的实体"""

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
    """2026-08-08 用于提交当前章 出现的全部实体（单列表）"""

    entities: list[EntityInput] = Field(default_factory=list)


# 2026-09-14 段落级情绪监督：句级口径退役，标签随指标整域提交。
# 2026-09-18 锚点口径改为"段首可见号"：注入正文每段以 `N：` 开头（N 为块内 1 基顺序号），
# 标签与 evidence 一律引用该号；落库时再映射回全局 paragraph_id（对持久化无影响）。
class ParagraphLabelInput(StrictModel):
    """一个段落的情绪标签

    paragraph_id 取正文段首可见号（每段开头的 `N：` 里那个 N）。
    """

    paragraph_id: int = Field(ge=1, description="段首可见号（正文每段开头的 `N：`）")
    emotion: int = Field(ge=-2, le=2, description=f"整段情绪分值。{EMOTION_SCORE_DESCRIPTION}")


class ChapterMetricsInput(StrictModel):
    """2026-08-07 用于提交当前章 摘要和叙事指标"""

    summary: str = Field(min_length=1)
    emotional_valence: int = Field(ge=-2, le=2, description=EMOTION_SCORE_DESCRIPTION)
    narrative_function: NarrativeFunction
    pivot_moment: bool = Field(default=False, description=PIVOT_MOMENT_DESCRIPTION)
    cliffhanger: bool = Field(default=False, description=CLIFFHANGER_DESCRIPTION)
    labels: list[ParagraphLabelInput] = Field(
        default_factory=list,
        description="段落级情绪标签（每章自选 2-3 段；按 paragraph_id 去重，重复提交以最后一次为准）",
    )

    @model_validator(mode="after")
    def normalize_summary(self) -> ChapterMetricsInput:
        """2026-08-07 用于规范化当前章 摘要；labels 按 paragraph_id 去重（后写覆盖）"""
        self.summary = normalize_semantic_text(self.summary, label="summary")
        deduped: dict[int, ParagraphLabelInput] = {}
        for label in self.labels:
            deduped[label.paragraph_id] = label
        self.labels = list(deduped.values())
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
    # 2026-09-14 枚举字段本身即拒绝非法词，不再叠函数级校验（越界值由类型报错，
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

    2026-09-13 小调用改造后只保留内部形态；2026-09-14 模型面参与记录由
    write_event 的 characters 数组提交（ParticipantArg），服务端在写入点把
    实体引用翻成规范名并组装成本形态。
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


# 2026-09-20 两个角色字段的判据（提示词面共用一份：载荷字段说明与程序面目录说明同取这里，
# 拒绝回执只报取值域）。run 54a72932 的 128 次 write_event 失败里，除漏填外主要是把身份
# 称号写进 role（如"大少爷"）与把 role 的词写进 narrative_role。
EVENT_ROLE_FIELD_HINT = "这个实体在这件事里起的作用，不是身份、称号"
PERSON_ROLE_FIELD_HINT = "与 role 同一判断的叙事面"


def _enum_values_text(enum_cls: type[StrEnum]) -> str:
    """用于把枚举成员渲染成取值域文本（提示词与回执的取值同取枚举，不手抄）"""
    return "、".join(str(member.value) for member in enum_cls)


class ParticipantArg(StrictModel):
    """事件的一个参与者（write_event.characters 数组元素）

    按该实体的登记类型分两种形态：character 填 entityid/role 加人物三态
    （narrative_role/action/emotion），其余实体只填 entityid/role。
    """

    entityid: EntityRef = Field(description=entity_ref_field_description("参与者实体引用"))
    role: EventParticipantRole = Field(
        description=(
            f"参与角色：{EVENT_ROLE_FIELD_HINT}；取 {_enum_values_text(EventParticipantRole)}"
            "（地点角色只用于 location 实体）"
        )
    )
    narrative_role: RoleFunction | None = Field(
        default=None,
        description=(
            f"仅 character 参与者必填的人物叙事功能（{PERSON_ROLE_FIELD_HINT}）："
            f"{_enum_values_text(RoleFunction)}"
        ),
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
    def normalize_participant(self) -> ParticipantArg:
        """2026-09-14 用于规范化动作并按组校验三态字段"""
        if self.action is not None:
            self.action = normalize_semantic_text(self.action, label="characters[].action")
        observation_fields = (self.narrative_role, self.action, self.emotion)
        if any(value is not None for value in observation_fields) and not all(
            value is not None for value in observation_fields
        ):
            raise ValueError("character 参与者的 narrative_role/action/emotion 必须同时提供；非 character 三者都不填")
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

    一棵树 = 一个完整事件；2026-09-14 起跨章因果链（cause_tree_id）退役，
    树不跨章，root_event_id/tree_id 仅服务于伏笔挂树。
    """

    tree_id: str = Field(min_length=1)
    chapter_id: int = Field(gt=0)
    chapter_order: int = Field(gt=0)
    description: str = Field(min_length=1)
    participants: list[dict[str, Any]] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 2026-09-13 伏笔入森林：树根视图携带伏笔属性（发现活跃伏笔的检索通道）
    foreshadowing_status: str | None = None
    payoff_likelihood: str | None = None
    cross_chapter: bool = False
    root_node_id: str = Field(min_length=1, description="树根节点 id（落库 event_id）")
    edges: list[dict[str, Any]] = Field(default_factory=list)


# 2026-09-18 段首可见号：正文段落若自带 `N：` 前缀则沿用该号，否则按顺序编 1 基号。
# 注入、evidence、标签三处共用这一个号码空间；全局 paragraph_id 只留在持久化侧。
_PARAGRAPH_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+)\s*：")


def paragraph_has_visible_prefix(text: str) -> bool:
    """2026-09-18 用于判断段落文本是否已自带 `N：` 段首号（注入时避免重复渲染）"""
    return _PARAGRAPH_NUMBER_PREFIX_RE.match(text) is not None


@dataclass(slots=True)
class ChapterParagraphInfo:
    """2026-08-18 用于保存当前 章内段落坐标映射（注入 prompt 标记和派生事件锚点）

    2026-09-18 锚点口径：模型可见的段落号是"段首可见号"——正文每段以 `N：` 开头
    （正文自带该前缀时沿用前缀里的号，否则按块内顺序编 1 基号）；evidence 与
    write_metrics.labels 都提交这个号，服务端按本映射取段落并映射回全局
    paragraph_id 再落库。三组列表内部仍按 0 基 章内序号索引。
    """

    # 0 基 章内序号 → 全局 paragraph_id
    paragraph_ids: list[int]
    # 0 基 章内序号 → (start_char, end_char) 在 章正文内的偏移
    char_spans: list[tuple[int, int]]
    # 0 基 章内序号 → 段落文本
    texts: list[str]

    def __post_init__(self) -> None:
        """2026-08-18 用于校验三组列表长度一致且非空"""
        n = len(self.paragraph_ids)
        if n == 0:
            raise ValueError("ChapterParagraphInfo 不能为空")
        if len(self.char_spans) != n or len(self.texts) != n:
            raise ValueError("paragraph_ids / char_spans / texts 长度不一致")

    def is_valid_index(self, index: int) -> bool:
        """2026-08-18 用于校验段落序号在当前章 范围内"""
        return 0 <= index < len(self.paragraph_ids)

    def visible_ids(self) -> list[int]:
        """2026-09-18 用于取每段的段首可见号（正文自带 N：前缀时用该号，否则 1 基顺序号）

        自带前缀出现重复号时退回纯 1 基顺序号：号码空间必须一对一，注入的正文
        与 evidence 锚点才不会有歧义。
        """
        ids: list[int] = []
        for index, text in enumerate(self.texts, start=1):
            match = _PARAGRAPH_NUMBER_PREFIX_RE.match(text)
            ids.append(int(match.group(1)) if match else index)
        if len(set(ids)) != len(ids):
            return list(range(1, len(self.texts) + 1))
        return ids

    def text_by_visible_id(self) -> dict[int, str]:
        """2026-09-18 用于取"段首可见号 → 段落文本"映射（evidence/标签按号取段）"""
        return dict(zip(self.visible_ids(), self.texts, strict=True))

    def global_id_for_visible(self, visible_id: int) -> int | None:
        """2026-09-18 用于把段首可见号映射回全局 paragraph_id（落库用）"""
        for candidate, global_id in zip(self.visible_ids(), self.paragraph_ids, strict=True):
            if candidate == visible_id:
                return int(global_id)
        return None

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
    # 2026-08-14 M7：允许负 chapter_id（子块运行时 ID，§20），候选不落库
    chapter_id: int
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
    """2026-08-11 用于系统绑定当前章 实体出现（与输入模型同构，标记已校验）"""


class BoundEntityDirectory(StrictModel):
    """2026-08-08 用于保存当前章 实体出现（单列表）"""

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
    """事件树节点（服务端派生角色、id；新节点绑定到本章具体段落）

    节点由 write_event 服务端生成：node_id 即最终落库 event_id。
    0.1.0 已有节点没有 evidence_paragraph_id，读取时保留原有章级证据。
    2026-09-14 写入面重构：cause_tree_id 退役（跨章因果边产生源下线，
    causal_event_refs 随之删除）；伏笔属性收敛为 is_foreshadow_setup +
    payoff_likelihood（值域 Confidence 三档，expected_payoff_family 列删）。
    """

    node_id: str = Field(min_length=1, description="服务端派生的节点 id（=落库 event_id）")
    tree_id: str = Field(min_length=1)
    parent_node_id: str | None = Field(default=None, description="root 为 None")
    cause_role: EventCauseRole
    description: str = Field(min_length=1)
    evidence_paragraph_id: int | None = Field(default=None, ge=0, description="事件所在段的全局段落 ID")
    participants: list[EventParticipantInput] = Field(default_factory=list)
    is_foreshadow_setup: bool = False
    # 2026-09-13 伏笔入森林：根事件携带伏笔属性（落库到 event_nodes 根列）
    payoff_likelihood: Confidence | None = None


class BoundRelation(RelationInput):
    """2026-08-07 用于系统注入关系方向和语义元数据"""

    directionality: Directionality
    relation_semantics: RelationSemantics


class BoundParagraphLabel(StrictModel):
    """2026-09-14 段落级情绪监督绑定结果（paragraph_id 已在账本校验属于本章，无需再绑字符区间）"""

    paragraph_id: int = Field(ge=0)
    emotion: int


class BoundChapterAnnotation(StrictModel):
    """2026-08-07 用于保存系统完成绑定的章节正式标注

    2026-09-19 章即块拍平：原 章级 BoundChunkAnnotation 并入本模型
    （每章一份正文，两级套娃退役）。图域（entities/relations）不是本模型的
    字段——实体与关系的运行时真相源是 FactGraph，持久化从其操作日志
    （entity_ops / relation_assert_ops / relation_change_ops）派生。

    2026-09-14 段落级监督：句级 sentence_labels 退役，段落情绪标签随
    write_metrics.labels 提交、账本校验段号后绑定成本模型；默认空列表
    保持 payload 反序列化兼容。
    """

    metrics: ChapterMetricsInput
    character_observations: list[BoundCharacterObservation]
    dialogues: list[BoundDialogue]
    events: list[BoundEvent]
    paragraph_labels: list[BoundParagraphLabel] = Field(default_factory=list)
    # 2026-09-05 冻结时系统确定性覆盖告警（如候选>0但载荷为空），仅留痕不阻断
    coverage_warnings: list[str] = Field(default_factory=list)


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
    chapter_id: int = Field(ge=0)
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


# 2026-09-18 把事件挂进既有伏笔树的两种动作：reinforce=该伏笔在本章继续发展 / payoff=兑现。
# 模型面取值清单与生产面校验共用这一份（写入路径与案例路径同一条语义）。
FORESHADOWING_ACTIONS: tuple[str, ...] = ("reinforce", "payoff")


class ResolvedCase(StrictModel):
    """2026-08-11 用于系统暂存 Agent 对活动案例的动作式解决结果

    2026-09-18 case_id 可空：空的表示这次动作**不是案例驱动的**（写入路径自己发起的关系
    变化 / 伏笔挂边 / 对话记录更新），此时不进案例锁定与解决映射，只走落库分派。
    """
    case_id: str = ""
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
    # 2026-09-14 expected_payoff_family 退役；payoff_likelihood 值域与 strength 同为 Confidence
    foreshadowing_action: Literal["reinforce", "payoff"] | None = None
    foreshadowing_root_event_id: str | None = None
    foreshadowing_event_id: str | None = None
    payoff_likelihood: str | None = None
    strength: str | None = None
    # 2026-09-18 promise 动作：案例由哪条产出记录交代（记录键，语义改动由那条记录自己承担）
    result_id: str | None = None

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
            # 2026-08-16 P3：枚举字段不再降级为 "unknown"，非法值直接拦截入库
            # 2026-09-14 payoff_likelihood 与 strength 值域统一为 Confidence 三档
            for field_name, valid_values in (
                (
                    "payoff_likelihood",
                    {confidence.value for confidence in Confidence},
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
        if self.action == "promise":
            if not (self.result_id or "").strip():
                raise ValueError("promise 动作必须提供 result_id（兑现该案例的产出记录键）")
            return self
        if self.action == "close":
            return self
        raise ValueError(f"未知案例动作: {self.action}")


class PendingCase(StrictModel):
    """2026-08-11 用于保存模型 push 登记的新连续性疑点案例"""

    type: CaseType
    # 2026-08-14 M7：允许负 chapter_id（子块运行时 ID，§20）；落库前由 workflow 映射回真实章节
    chapter_id: int
    keys: list[str] = Field(min_length=1)
    description: str = Field(min_length=1, max_length=100)
    target_key: str
    target_ref: dict[str, Any]


class AgentRunAudit(StrictModel):
    """2026-08-19 用于保存系统范围搜索凭据和领域写入记录（完整工具审计进入新审计表）

    2026-08-30：文本检索返回正文时即时登记精确段落授权。
    2026-09-19 sub_chunk_index 字段随子块协议退役删除（子块不再是运行单元）。
    """

    allow_future_context: bool
    write_records: list[dict[str, Any]]
    authorized_chapter_ids: list[int]
    authorized_text_paragraph_ids: list[int]
    # 2026-08-18 P2：历史事件只能使用本轮 search_event_history 返回的稳定 ID
    authorized_event_ids: list[str] = Field(default_factory=list)
    closed_case_ids: list[str] = Field(default_factory=list)


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
    chapter_id: int = Field(ge=0)
    keys: list[str]
    description: str
    target_ref: dict[str, Any]
    state: CaseState


class CompletionResolvedCase(StrictModel):
    """2026-08-11 用于返回完成事务按 action 写入的解决目标（close 动作无目标）

    2026-09-18：promise 动作的目标是一条产出记录（记录键），不是库内行。
    """

    case_id: str
    action: CaseAction
    type: CaseType
    reason: str
    target_dialogue_id: str | None = None
    target_fact_id: str | None = None
    # 2026-09-13 伏笔入森林：解决目标是伏笔树根与挂进树的事件
    target_root_event_id: str | None = None
    target_event_id: str | None = None
    target_record_id: str | None = None


class CompletionResult(StrictModel):
    """2026-08-07 用于回读或返回章节唯一完成事务"""

    annotation_id: str
    chapter_id: int = Field(gt=0)
    created_cases: list[CompletionCase] = Field(default_factory=list)
    resolved_cases: list[CompletionResolvedCase] = Field(default_factory=list)
