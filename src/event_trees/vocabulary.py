"""
事件值域：子事件在树内的位置、参与实体在事件里的角色，以及参与角色的归一

说明: 事件专属值域随写入目标（事件树）同包；实体/关系/对话/指标值域在
src/fact_graph/vocabulary.py。本模块只有标准库依赖。
"""

from __future__ import annotations

import unicodedata
from enum import StrEnum
from typing import Literal

# 2026-08-30 事件参与者专属角色词不能写进同一参与者的人物功能字段
# （2026-09-11 见证者已并入 RoleFunction 词表，从拒绝表移除）
_EVENT_ONLY_ROLE_WORDS = frozenset({"地点", "行动者", "承受者", "协助者", "对抗者"})


class EventChildType(StrEnum):
    """子事件在树内的位置

    main=顺延主因链（成为新的链尾）；secondary=挂在当时主链尾（次因分支）。
    """

    MAIN = "main"
    SECONDARY = "secondary"


# 2026-08-19 事件树内部节点角色（一棵树 = 一个完整事件；根 = 触发该
# 事件的第一个自立动作；main = 主因链上；secondary = 父的兄弟即次因分支）
# 2026-09-14 模型面 type 参数用 EventChildType（root 由 isroot=true 表达，不外露）
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
