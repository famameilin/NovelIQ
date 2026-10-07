"""内部常量与文本归一化规则"""

from __future__ import annotations

from src.config.constants.diagnosis import GENRE_LABEL_VALUES, STYLE_LABEL_VALUES
from src.config.constants.progress import STAGE_PROGRESS_MILESTONES
from src.config.constants.text_normalization import (
    ALLOWED_PREV_CJK_CHARS,
    LIKELY_NAME_PREFIX_CHARS,
    TITLE_ALIAS_SUFFIXES,
)
from src.lexicons.constants import LEXICON_DRAFT_KEYS, LEXICON_FILES, SEMANTIC_CATEGORY_MAPPING

PROPP_FUNCTIONS: set[str] = {
    "主体",
    "客体",
    "发送者",
    "接收者",
    "帮助者",
    "反对者",
    "其他",
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
    "GENRE_LABEL_VALUES",
    "STYLE_LABEL_VALUES",
]
