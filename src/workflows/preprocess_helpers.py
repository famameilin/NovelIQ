"""
预处理辅助函数模块 (workflows层)

包含预处理的核心业务逻辑函数，纯业务逻辑、不依赖入口层，可被多个入口点复用。

2026-08-14 M8b：_compute_chunk_style_metrics（chunk_style 链）已删除——
风格指标以 paragraph_metrics 的充分统计量为事实源。
2026-08-15 词表 v3：词表数据在 src/lexicons/tables 模块级加载为常量，
本函数仅按段落链契约组装，不再经 registry 读取。
"""

from __future__ import annotations

from typing import Any

from src.lexicons.tables import (
    COMBAT_TERMS,
    FUNCTION_WORDS_TERMS,
    IMAGERY_TERMS,
    NEGATIVE_TERMS,
    POSITIVE_TERMS,
    SEMANTIC_CATEGORIES,
    SENSORY_TERMS,
)


def _load_all_lexicons_for_preprocess() -> dict[str, list[str] | dict[str, Any]]:
    """
    加载所有词典用于预处理

    词表数据来自 tables 常量（registry 一次性读取）：
    - pos/neg 为加权 dict（M4 弃用权重后改词条集合统一 1.0）
    - 战斗词条只取词条键，权重不参与密度计算，统一按 1.0 登记
    - semantic_categories 为类别标题解析后的分类字典
    """
    lexicons: dict[str, list[str] | dict[str, Any]] = {}
    lexicons["sensory"] = SENSORY_TERMS
    lexicons["function_words"] = FUNCTION_WORDS_TERMS
    lexicons["imagery"] = IMAGERY_TERMS
    # 战斗词条用于 fight_density（tension_proxy 只取词条键，
    # 权重不参与密度计算，统一按 1.0 登记）
    lexicons["fight_terms"] = dict.fromkeys(COMBAT_TERMS, 1.0)
    # 段落情绪分子（§5.3 positive/negative_weight_sum）：加权词表（v3 过渡期，
    # M4 弃用权重后改词条集合统一 1.0）
    lexicons["pos_terms"] = POSITIVE_TERMS
    lexicons["neg_terms"] = NEGATIVE_TERMS
    lexicons["semantic_categories"] = SEMANTIC_CATEGORIES

    return lexicons
