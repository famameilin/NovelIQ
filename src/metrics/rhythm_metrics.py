from __future__ import annotations

from typing import Dict, Iterable, List

from .lexicon_metrics import count_mixed_hits
from .text_utils import dialogue_length, split_sentences, tokenize_words


def tension_proxy(text: str, fight_terms: Iterable[str]) -> Dict[str, float]:
    """
    计算张力代理指标

    创建时间: 2025-03-11
    创建者: TraeAI
    任务: 预处理流程
    说明: 计算战斗密度、感叹密度、问句密度等指标。

    修改时间: 2026-03-26
    修改者: TraeAI
    任务: 修复 fight_density 重叠计数问题
    修改内容: 使用 count_mixed_hits 替代 count_hits，避免重叠词重复计数；
              统一量纲为词数，与其他密度指标保持一致。
    """
    if not text:
        return {
            "avg_sent_len": 0.0,
            "fight_density": 0.0,
            "exclaim_density": 0.0,
            "dialogue_ratio": 0.0,
            "question_density": 0.0,
        }
    sentences = split_sentences(text)
    avg_sent_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
    tokens = tokenize_words(text)
    token_count = max(len(tokens), 1)
    fight_density = count_mixed_hits(text, tokens, fight_terms) / token_count
    exclaim_density = text.count("！") / token_count
    question_density = text.count("？") / token_count
    dialogue_ratio = dialogue_length(text) / len(text)
    return {
        "avg_sent_len": avg_sent_len,
        "fight_density": fight_density,
        "exclaim_density": exclaim_density,
        "dialogue_ratio": dialogue_ratio,
        "question_density": question_density,
    }


def tension_composite(signals: List[Dict[str, float]]) -> List[float]:
    if not signals:
        return []
    keys = ["avg_sent_len", "fight_density", "exclaim_density", "dialogue_ratio", "question_density"]
    mins = {key: min(item.get(key, 0.0) for item in signals) for key in keys}
    maxs = {key: max(item.get(key, 0.0) for item in signals) for key in keys}
    composites: List[float] = []
    for item in signals:
        total = 0.0
        for key in keys:
            value = item.get(key, 0.0)
            denom = maxs[key] - mins[key]
            if denom == 0:
                normalized = 0.0
            else:
                normalized = (value - mins[key]) / denom
            if key == "avg_sent_len":
                normalized = 1.0 - normalized
            total += normalized
        composites.append(total / len(keys))
    return composites
