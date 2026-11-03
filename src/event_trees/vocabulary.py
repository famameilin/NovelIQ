"""事件位置、参与功能、情绪与伏笔值域"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Literal

# 事件参与者专属角色词不能写进同一参与者的人物功能字段
_EVENT_ONLY_ROLE_WORDS = frozenset({"地点", "行动者", "承受者", "协助者", "对抗者"})


class EventChildType(StrEnum):
    """子事件在树内的位置

    main=顺延主因链（成为新的链尾）；secondary=挂在当时主链尾（次因分支）。
    """

    MAIN = "main"
    SECONDARY = "secondary"


# 事件内部原因角色；模型面只使用 EventChildType，不暴露该枚举
EventCauseRole = Literal["root", "main", "secondary"]


class EventParticipantRole(StrEnum):
    """参与实体在这次事件里的角色

    主体=事件的发起者；客体=事件的承受者；接收者=接收对象；帮助者=协助主体的人；
    反对者=阻碍事件的人；见证者=在场但未介入的人；地点=事件发生的场所（location 或 organization 实体）。
    """

    SUBJECT = "主体"
    OBJECT = "客体"
    RECEIVER = "接收者"
    HELPER = "帮助者"
    OPPONENT = "反对者"
    WITNESS = "见证者"
    LOCATION = "地点"


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


class Confidence(StrEnum):
    """伏笔的可能性档位

    high=正文有明确指向该伏笔的表述；medium=有较明显的暗示但没有点明；
    low=只是可疑的苗头，是否成立取决于后文。
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


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
    （原始入参始终在 agent_toolcall.request_args 可查）。地点等事件专属角色词
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


EMOTION_SCORE_DESCRIPTION = (
    "情绪方向与强度分值，整数 -2..2（-2 强烈负面 / -1 轻微负面 / 0 中性 / 1 轻微正面 / 2 强烈正面）"
)


EVENT_ROLE_FIELD_HINT = "这个实体在这件事里起的作用，不是身份、称号"


PERSON_ROLE_FIELD_HINT = "与 role 同一判断的叙事面"
