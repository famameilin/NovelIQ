"""
张力代理指标计算模块

计算战斗密度、感叹密度、问句密度等张力代理指标。


"""

from __future__ import annotations

from .matching import count_token_hits_enhanced
from .text_utils import dialogue_length, split_sentences, tokenize_words


def tension_proxy(text: str, fight_terms: dict[str, float]) -> dict[str, float]:
    """
    计算张力代理指标。

    使用 fuzzy 模式匹配，支持分词变体（如"剑气"/"剑罡"）
    - 子串匹配（如"冷笑"被分词为"冷"+"笑"时仍能匹配）
    - 编辑距离容错（如"剑罡"匹配"剑气"）

    参数:
        text: 原始文本
        fight_terms: 战斗词条集合，格式为 {词条: 权重}

    返回:
        dict[str, float]: 包含 fight_density, exclaim_density, question_density, dialogue_ratio, avg_sent_len


    """
    if not text:
        return {
            "fight_density": 0.0,
            "exclaim_density": 0.0,
            "question_density": 0.0,
            "dialogue_ratio": 0.0,
            "avg_sent_len": 0.0,
        }

    tokens = tokenize_words(text)
    token_count = max(len(tokens), 1)

    fight_count = count_token_hits_enhanced(text, tokens, list(fight_terms.keys()), mode="fuzzy")
    fight_density = fight_count / token_count

    exclaim_count = text.count("!") + text.count("！")
    exclaim_density = exclaim_count / token_count

    question_count = text.count("?") + text.count("？")
    question_density = question_count / token_count

    dialogue_len = dialogue_length(text)
    dialogue_ratio = dialogue_len / len(text) if len(text) > 0 else 0.0

    sentences = split_sentences(text)
    avg_sent_len = sum(len(s) for s in sentences) / len(sentences) if sentences else 0.0

    return {
        "fight_density": fight_density,
        "exclaim_density": exclaim_density,
        "question_density": question_density,
        "dialogue_ratio": dialogue_ratio,
        "avg_sent_len": avg_sent_len,
    }


def tension_composite(
    fight_density: float,
    exclaim_density: float,
    question_density: float,
    dialogue_ratio: float,
    avg_sent_len: float,
) -> float:
    """
    计算张力综合指标。

    公式:
            0.4 * fight_density
            + 0.2 * exclaim_density
            + 0.2 * question_density
            + 0.1 * dialogue_ratio
            + 0.1 * avg_sent_len_normalized

    参数:
        fight_density: 战斗密度
        exclaim_density: 感叹密度
        question_density: 问句密度
        dialogue_ratio: 对话比例
        avg_sent_len: 平均句长

    返回:
        float: 张力综合指标
    """
    avg_sent_len_normalized = min(avg_sent_len / 50.0, 1.0)
    return (
        0.4 * fight_density
        + 0.2 * exclaim_density
        + 0.2 * question_density
        + 0.1 * dialogue_ratio
        + 0.1 * avg_sent_len_normalized
    )
