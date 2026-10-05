"""
章节标注 Agent 语义词表：枚举、Literal 取值域、实体类型组与闭合关系目录
"""

# 创建时间：2026-10-02　创建者：Trae
# 任务：schema.py 大文件拆分——原枚举/Literal/关系目录段迁入本模块
# 说明：纯结构搬移，不改任何运行逻辑与签名；schema.py 对全部符号保留 re-export，
# 既有导入方零改动。依赖方向：vocabulary ← inputs ← outputs，本模块不反向依赖。
# 模型可见文案约定沿用 schema 模块头：类 docstring 会进模型可见面，一律按"说明"写。

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Literal, TypedDict

# 2026-08-30 事件参与者专属角色词不能写进同一参与者的人物功能字段
# （2026-09-11 见证者已并入 RoleFunction 词表，从拒绝表移除）
_EVENT_ONLY_ROLE_WORDS = frozenset({"地点", "行动者", "承受者", "协助者", "对抗者"})


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
    not_dialogue=信件、便条、书籍引文、书名、术语强调及假设性台词。
    口头转述或回忆中确实说过的话仍判 dialogue；书面内容保留在事件或证据中。
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


# 2026-10-04 合同由"缺失/越界即拒"改"缺省归一"（run 08f9ba42 审计：participants 族
# 拒绝 482 次=全部被拒 53%，且是子代理盲发死循环的唯一燃料）。两条生产路径共用。
ROLE_FUNCTION_ALIASES: dict[str, str] = {
    "主角": "主体",
    "发起者": "主体",
    "发起人": "主体",
    "施动者": "主体",
    "承受者": "客体",
    "受动者": "客体",
    "接受者": "接收者",
    "协助者": "帮助者",
    "支持者": "帮助者",
    "阻碍者": "反对者",
    "对抗者": "反对者",
    "旁观者": "见证者",
    "目击者": "见证者",
    "在场者": "见证者",
}


def normalize_role_function(value: object) -> RoleFunction | None:
    """用于把模型写的叙事功能词归一到 RoleFunction（缺省/未收录不拒绝）

    同义词按 ROLE_FUNCTION_ALIASES 映射；未收录值收敛为主体并留给审计
    （原始入参始终在 agent_tool_calls.request_args 可查）。地点等事件专属角色词
    不在此处理——那是字段误用，仍由调用方按原口径拒绝。
    """
    if value is None:
        return None
    if isinstance(value, RoleFunction):
        return value
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value).strip()
    if not text:
        return None
    text = ROLE_FUNCTION_ALIASES.get(text, text)
    try:
        return RoleFunction(text)
    except ValueError:
        return RoleFunction.SUBJECT


def normalize_event_participant_role(value: object) -> EventParticipantRole | None:
    """用于把模型写的参与角色词归一到 EventParticipantRole（缺省/未收录返回 None）

    None 由生产面按实体登记类型给缺省（character→主体、location→地点、其余→客体）。
    """
    if value is None:
        return None
    if isinstance(value, EventParticipantRole):
        return value
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFC", value).strip()
    if not text:
        return None
    try:
        return EventParticipantRole(text)
    except ValueError:
        return None


def clamp_emotion_score(value: object) -> int | None:
    """用于把模型写的情绪分值收敛到 -2..2（越界按边界钳制，非数值记空）"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    return max(-2, min(2, round(value)))


class RelationChangeKind(StrEnum):
    """2026-08-07 用于约束关系事实的生命周期变化（系统内部、持久化与 API 使用的英文值域）"""

    ASSERT = "assert"
    REINFORCE = "reinforce"
    WEAKEN = "weaken"
    BREAK = "break"
    REFINE = "refine"
    SUPERSEDE = "supersede"
    RETRACT = "retract"


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
