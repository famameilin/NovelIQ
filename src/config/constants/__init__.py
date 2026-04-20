"""
系统常量 - 不适合用户手动配置的内部常量

创建时间: 2026-03-27
创建者: TraeAI
任务: consolidate-codebase-architecture
说明: 整合原 constants.py 和新增的文本归一化常量
"""

from __future__ import annotations

import re

from src.config.constants.annotation import (
    EMOTION_SCORE_MAPPING,
    SYMMETRIC_RELATION_TYPES,
    VALID_ACTION_TYPES,
    VALID_CHANGE_TYPES,
    VALID_CLUE_TYPES,
    VALID_EMOTION_SCORES,
    VALID_ENTITY_TYPES,
    VALID_EVENT_TYPES,
    VALID_FORESHADOWING_TYPES,
    VALID_RELATION_TYPES,
    VALID_ROLE_FUNCTIONS,
)
from src.config.constants.text_normalization import (
    ALLOWED_PREV_CJK_CHARS,
    LIKELY_NAME_PREFIX_CHARS,
    TITLE_ALIAS_SUFFIXES,
)

EVENT_TYPE_SCORES: dict[str, float] = {
    "高潮": 1.0,
    "冲突": 0.8,
    "转折": 0.6,
    "铺垫": 0.4,
    "日常": 0.2,
}

THREE_ACT_MAPPING: dict[str, str] = {
    "铺垫": "act1",
    "日常": "act1",
    "转折": "act2",
    "冲突": "act2",
    "高潮": "act3",
}

PROPP_FUNCTIONS: set[str] = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
    "其他",
}

CLASSICAL_PATTERNS: list[str] = [
    r"之[^\s]{0,3}[者也乎哉]",
    r"[岂宁庸]不[^\s]{0,5}[耶乎哉]",
    r"[乃则]若[^\s]{0,5}[者也]",
    r"[因遂乃]即[^\s]{0,5}[者也乎]",
    r"何[^\s]{0,3}[耶乎哉兮]",
    r"[呜噫嗟夫][^\s]{0,3}[哉兮也]",
]

SEMANTIC_CATEGORY_MAPPING: dict[str, str] = {
    "武功武器类": "combat",
    "身体部件类": "body",
    "人物关系类": "relation",
    "门派派系类": "faction",
    "使令动词类": "command",
    "动作动词类": "action",
    "心理动词类": "psychology",
    "度量形容词类": "measure",
    "情绪形容词类": "emotion",
    "色彩形容词类": "color",
}

CHAPTER_PATTERN = re.compile(r"(^|[\r\n])\s*第.{1,9}章[^\r\n]*")
PARAGRAPH_SPLIT = re.compile(r"(?:\r\n|\r|\n)+")

__all__ = [
    "EVENT_TYPE_SCORES",
    "THREE_ACT_MAPPING",
    "PROPP_FUNCTIONS",
    "CLASSICAL_PATTERNS",
    "SEMANTIC_CATEGORY_MAPPING",
    "CHAPTER_PATTERN",
    "PARAGRAPH_SPLIT",
    "TITLE_ALIAS_SUFFIXES",
    "ALLOWED_PREV_CJK_CHARS",
    "LIKELY_NAME_PREFIX_CHARS",
    "EMOTION_SCORE_MAPPING",
    "VALID_ROLE_FUNCTIONS",
    "VALID_ACTION_TYPES",
    "VALID_EMOTION_SCORES",
    "VALID_ENTITY_TYPES",
    "VALID_CLUE_TYPES",
    "VALID_EVENT_TYPES",
    "VALID_FORESHADOWING_TYPES",
    "SYMMETRIC_RELATION_TYPES",
    "VALID_RELATION_TYPES",
    "VALID_CHANGE_TYPES",
]
