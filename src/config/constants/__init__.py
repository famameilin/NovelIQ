"""内部常量与文本归一化规则"""

from __future__ import annotations

from src.config.constants.lexicons import LEXICON_DRAFT_KEYS, LEXICON_FILES
from src.config.constants.progress import STAGE_PROGRESS_MILESTONES
from src.config.constants.text_normalization import (
    ALLOWED_PREV_CJK_CHARS,
    LIKELY_NAME_PREFIX_CHARS,
    TITLE_ALIAS_SUFFIXES,
)

PROPP_FUNCTIONS: set[str] = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
    "其他",
}

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

__all__ = [
    "PROPP_FUNCTIONS",
    "SEMANTIC_CATEGORY_MAPPING",
    "TITLE_ALIAS_SUFFIXES",
    "ALLOWED_PREV_CJK_CHARS",
    "LIKELY_NAME_PREFIX_CHARS",
    "STAGE_PROGRESS_MILESTONES",
    "LEXICON_FILES",
    "LEXICON_DRAFT_KEYS",
]
