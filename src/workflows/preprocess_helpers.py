"""
预处理辅助函数模块 (workflows层)

创建时间: 2026-03-14
创建者: TraeAI
任务: 从 cli 提取核心业务逻辑到 workflows 层
说明: 此文件从 src/cli/preprocess_helpers.py 复制而来，包含预处理的核心业务逻辑函数。
      这些函数是纯业务逻辑，不依赖CLI层，可被多个入口点复用。
原始文件: src/cli/preprocess_helpers.py

修改时间: 2026-03-15
修改者: TraeAI
任务: storage-layer-decoupling
修改内容: 从 repositories 导入 ChunkStyleData，避免触发 operations 的 deprecation warning
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from src.chunking.chunker import Chunk
from src.lexicons.loader import load_lexicon
from src.metrics.style_metrics import (
    dialogue_ratio,
    function_word_distribution,
    metaphor_density,
    mtld,
    parse_semantic_category_lexicon,
    pause_density,
    semantic_category_densities,
    sentence_length_stats,
    ttr,
)
from src.storage.repositories import ChunkStyleData


def _load_all_lexicons_for_preprocess(lexicon_dir: Path) -> dict[str, list[str] | dict[str, list[str]]]:
    """
    加载所有词典用于预处理

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_preprocess 中提取，负责加载所有需要的词典

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除文化词表加载，只保留 imagery 词表
    """
    lexicons: dict[str, list[str] | dict[str, list[str]]] = {}

    try:
        lexicons["sensory"] = load_lexicon("sensory", lexicon_dir)
    except FileNotFoundError:
        lexicons["sensory"] = []
        logger.warning("sensory lexicon not found")

    try:
        lexicons["function_words"] = load_lexicon("function_words", lexicon_dir)
    except FileNotFoundError:
        lexicons["function_words"] = []
        logger.warning("function_words lexicon not found")

    try:
        lexicons["imagery"] = load_lexicon("imagery", lexicon_dir)
    except FileNotFoundError:
        lexicons["imagery"] = []
        logger.warning("imagery lexicon not found")

    semantic_category_file = lexicon_dir / "semantic_category.txt"
    if semantic_category_file.exists():
        lexicons["semantic_categories"] = parse_semantic_category_lexicon(str(semantic_category_file))
    else:
        lexicons["semantic_categories"] = {}
        logger.warning("semantic_category lexicon not found")

    return lexicons


def _compute_chunk_style_metrics(
    chunk: Chunk,
    tokens: list[str],
    sensory_terms: list[str],
    function_words: list[str],
    semantic_categories: dict,
) -> ChunkStyleData:
    """
    计算单个chunk的风格指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_preprocess 中提取，负责计算chunk的风格指标
    """
    from src.metrics.style_metrics import sensory_density

    mtld_val = mtld(tokens)
    ttr_val = ttr(tokens)
    sent_stats = sentence_length_stats(chunk.text)
    pause_val = pause_density(chunk.text)
    dialogue_val = dialogue_ratio(chunk.text)
    metaphor_val = metaphor_density(chunk.text)

    sensory_val = 0.0
    if sensory_terms:
        sensory_val = sensory_density(chunk.text, sensory_terms)

    fw_dist = {}
    if function_words:
        fw_dist = function_word_distribution(tokens, function_words)
    fw_vector_json = json.dumps(fw_dist, ensure_ascii=False) if fw_dist else "{}"

    cat_densities = {}
    if semantic_categories:
        cat_densities = semantic_category_densities(chunk.text, semantic_categories)

    return ChunkStyleData(
        chunk_id=chunk.index,
        mtld=mtld_val,
        ttr=ttr_val,
        avg_sent_len=sent_stats["avg_sent_len"],
        sent_len_std=sent_stats["sent_len_std"],
        d_value=sent_stats["d_value"],
        pause_density=pause_val,
        fight_density=0.0,
        exclaim_density=0.0,
        dialogue_ratio=dialogue_val,
        question_density=0.0,
        sensory_density=sensory_val,
        metaphor_density=metaphor_val,
        function_word_vector=fw_vector_json,
        category_density_combat=cat_densities.get("combat", 0.0),
        category_density_body=cat_densities.get("body", 0.0),
        category_density_relation=cat_densities.get("relation", 0.0),
        category_density_faction=cat_densities.get("faction", 0.0),
        category_density_command=cat_densities.get("command", 0.0),
        category_density_action=cat_densities.get("action", 0.0),
        category_density_psychology=cat_densities.get("psychology", 0.0),
        category_density_measure=cat_densities.get("measure", 0.0),
        category_density_emotion=cat_densities.get("emotion", 0.0),
        category_density_color=cat_densities.get("color", 0.0),
    )


def _compute_chunk_culture_metrics(
    chunk: Chunk,
    tokens: list[str],
    imagery_terms: list[str],
) -> tuple[int, float | None]:
    """
    计算单个chunk的文化指标

    创建时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-analysis-layer-functions
    说明: 从 run_preprocess 中提取，负责计算chunk的文化指标

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 简化文化指标系统
    修改内容: 删除低价值词表密度计算，只保留 imagery_lexicon_density
    """
    from src.metrics.style_metrics import imagery_density

    imagery_lexicon_val = imagery_density(chunk.text, imagery_terms) if imagery_terms else None

    return (
        chunk.index,
        imagery_lexicon_val,
    )
