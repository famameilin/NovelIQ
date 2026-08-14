"""
预处理辅助函数模块 (workflows层)

包含预处理的核心业务逻辑函数，纯业务逻辑、不依赖入口层，可被多个入口点复用。

2026-08-14 M8b：_compute_chunk_style_metrics（chunk_style 链）已删除——
风格指标以 paragraph_metrics 的充分统计量为事实源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.lexicons.registry import LexiconRegistry
from src.metrics.style_metrics import parse_semantic_category_lexicon


def _load_all_lexicons_for_preprocess(
    lexicon_dir: Path,
) -> dict[str, list[str] | dict[str, Any]]:
    """
    加载所有词典用于预处理

    从 run_preprocess 中提取，负责加载所有需要的词典

    """
    registry = LexiconRegistry(base_dir=lexicon_dir)
    registry.load()

    lexicons: dict[str, list[str] | dict[str, Any]] = {}
    lexicons["sensory"] = registry.get("style.sensory_5sense")
    lexicons["function_words"] = registry.get("style.function_words")
    lexicons["imagery"] = registry.get("culture.imagery")
    # 2026-08-13 P2-4 战斗词条用于 fight_density（tension_proxy 只取词条键，
    # 权重不参与密度计算，统一按 1.0 登记）
    lexicons["fight_terms"] = dict.fromkeys(registry.get("tension.action_terms"), 1.0)
    # 2026-08-14 段落情绪分子（§5.3 positive/negative_weight_sum）：
    # 使用带权重的正负情感词表，权重参与加权求和
    from src.utils.lexicon_parser import load_weighted_lexicon

    positive_file = lexicon_dir / "positive.txt"
    negative_file = lexicon_dir / "negative.txt"
    lexicons["pos_terms"] = (
        load_weighted_lexicon(str(positive_file)) if positive_file.exists() else {}
    )
    lexicons["neg_terms"] = (
        load_weighted_lexicon(str(negative_file)) if negative_file.exists() else {}
    )

    # semantic_category 需要解析为分类字典

    semantic_category_file = lexicon_dir / "semantic_category.txt"
    if semantic_category_file.exists():
        lexicons["semantic_categories"] = parse_semantic_category_lexicon(str(semantic_category_file))
    else:
        lexicons["semantic_categories"] = {}

    return lexicons
