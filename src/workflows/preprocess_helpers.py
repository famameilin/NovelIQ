"""
预处理辅助函数模块 (workflows层)

此文件从 src/cli/preprocess_helpers.py 复制而来，包含预处理的核心业务逻辑函数。
      这些函数是纯业务逻辑，不依赖CLI层，可被多个入口点复用。
原始文件: src/cli/preprocess_helpers.py

"""

from __future__ import annotations

import json
from pathlib import Path

from src.chunking.chunker import Chunk
from src.lexicons.registry import LexiconRegistry
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

    从 run_preprocess 中提取，负责加载所有需要的词典

    """
    registry = LexiconRegistry(base_dir=lexicon_dir)
    registry.load()

    lexicons: dict[str, list[str] | dict[str, list[str]]] = {}
    lexicons["sensory"] = registry.get("style.sensory_5sense")
    lexicons["function_words"] = registry.get("style.function_words")
    lexicons["imagery"] = registry.get("culture.imagery")

    # semantic_category 需要解析为分类字典

    semantic_category_file = lexicon_dir / "semantic_category.txt"
    if semantic_category_file.exists():
        lexicons["semantic_categories"] = parse_semantic_category_lexicon(str(semantic_category_file))
    else:
        lexicons["semantic_categories"] = {}

    return lexicons


def _compute_chunk_style_metrics(
    chunk: Chunk,
    tokens: list[str],
    sensory_terms: list[str],
    function_words: list[str],
    semantic_categories: dict,
    imagery_terms: list[str],
) -> ChunkStyleData:
    """
    计算单个chunk的风格指标

    从 run_preprocess 中提取，负责计算chunk的风格指标

    """
    from src.metrics.style_metrics import imagery_density, sensory_density

    mtld_val = mtld(tokens)
    ttr_val = ttr(tokens)
    sent_stats = sentence_length_stats(chunk.text)
    pause_val = pause_density(chunk.text)
    dialogue_val = dialogue_ratio(chunk.text)
    metaphor_val = metaphor_density(chunk.text)

    sensory_val = 0.0
    if sensory_terms:
        sensory_val = sensory_density(chunk.text, sensory_terms)
    imagery_lexicon_val = imagery_density(chunk.text, imagery_terms) if imagery_terms else None

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
        imagery_lexicon_density=imagery_lexicon_val,
    )
