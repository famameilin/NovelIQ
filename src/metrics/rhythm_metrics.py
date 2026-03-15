from __future__ import annotations

from typing import Dict, Iterable, List

from .lexicon_metrics import count_hits
from .text_utils import dialogue_length, split_sentences


def tension_proxy(text: str, fight_terms: Iterable[str]) -> Dict[str, float]:
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
    text_len = len(text)
    fight_density = count_hits(text, fight_terms) / text_len
    exclaim_density = text.count("！") / text_len
    question_density = text.count("？") / text_len
    dialogue_ratio = dialogue_length(text) / text_len
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
