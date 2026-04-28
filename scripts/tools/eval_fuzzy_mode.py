"""
Fuzzy 模式效果评估脚本

对比 exact/phrase/fuzzy 三种模式在真实小说数据上的召回率
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.lexicons.registry import LexiconRegistry
from src.metrics.matching import count_token_hits_enhanced
from src.metrics.text_utils import tokenize_words

if TYPE_CHECKING:
    from collections.abc import Sequence


def evaluate_fuzzy_mode(
    text: str,
    terms: Sequence[str],
    modes: list[str] | None = None,
) -> dict[str, int]:
    """
    评估不同匹配模式在给定文本上的命中数

    Args:
        text: 待评估文本
        terms: 词条集合
        modes: 要评估的模式列表，默认为 ["exact", "phrase", "fuzzy"]

    Returns:
        各模式的命中数字典
    """
    if modes is None:
        modes = ["exact", "phrase", "fuzzy"]

    tokens = tokenize_words(text)
    results = {}

    for mode in modes:
        try:
            count = count_token_hits_enhanced(text, tokens, terms, mode=mode)
            results[mode] = count
        except ValueError as e:
            results[mode] = -1

    return results


def sample_battle_texts(novel_path: Path, sample_size: int = 10) -> list[str]:
    """
    从小说中采样包含战斗术语的片段

    Args:
        novel_path: 小说文件路径
        sample_size: 采样数量

    Returns:
        采样片段列表
    """
    import re

    battle_keywords = [
        "剑气",
        "刀光",
        "拳风",
        "掌力",
        "内力",
        "真气",
        "灵力",
        "法术",
        "攻击",
        "防御",
        "战斗",
        "杀",
        "斩",
        "劈",
        "刺",
    ]

    with open(novel_path, encoding="utf-8") as f:
        try:
            content = f.read()
        except UnicodeDecodeError:
            with open(novel_path, encoding="gbk") as f2:
                content = f2.read()

    paragraphs = re.split(r"\n+", content)

    battle_paragraphs = []
    for p in paragraphs:
        if len(p) < 50 or len(p) > 500:
            continue
        for kw in battle_keywords:
            if kw in p:
                battle_paragraphs.append(p)
                break

    import random

    if len(battle_paragraphs) > sample_size:
        return random.sample(battle_paragraphs, sample_size)
    return battle_paragraphs


def run_evaluation(novel_dir: Path, output_path: Path | None = None) -> dict:
    """
    运行完整评估流程

    Args:
        novel_dir: 小说目录
        output_path: 输出报告路径（可选）

    Returns:
        评估结果字典
    """
    registry = LexiconRegistry()
    registry.load()

    fight_terms = registry.get_with_domains("tension.action_terms", ["power_struggle"])

    novel_files = list(novel_dir.glob("*.txt"))
    if not novel_files:
        return {"error": "No novel files found"}

    all_results = []
    total_counts = {"exact": 0, "phrase": 0, "fuzzy": 0}

    for novel_file in novel_files[:2]:
        samples = sample_battle_texts(novel_file, sample_size=5)
        for i, text in enumerate(samples):
            result = evaluate_fuzzy_mode(text, fight_terms)
            result["text_preview"] = text[:50] + "..." if len(text) > 50 else text
            result["source"] = novel_file.name
            all_results.append(result)

            for mode in ["exact", "phrase", "fuzzy"]:
                total_counts[mode] += result.get(mode, 0)

    recall_improvement = {
        "phrase_vs_exact": (
            (total_counts["phrase"] - total_counts["exact"]) / max(total_counts["exact"], 1) * 100
        ),
        "fuzzy_vs_exact": (
            (total_counts["fuzzy"] - total_counts["exact"]) / max(total_counts["exact"], 1) * 100
        ),
        "fuzzy_vs_phrase": (
            (total_counts["fuzzy"] - total_counts["phrase"]) / max(total_counts["phrase"], 1) * 100
        ),
    }

    summary = {
        "total_samples": len(all_results),
        "total_hits": total_counts,
        "recall_improvement_percent": recall_improvement,
        "sample_results": all_results[:5],
    }

    if output_path:
        import json

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


if __name__ == "__main__":
    novel_dir = Path("data/novel")
    output_path = Path("docs/fuzzy_mode_evaluation.json")

    print("=" * 60)
    print("Fuzzy 模式效果评估")
    print("=" * 60)

    result = run_evaluation(novel_dir, output_path)

    if "error" in result:
        print(f"错误: {result['error']}")
    else:
        print(f"\n总样本数: {result['total_samples']}")
        print(f"\n各模式总命中数:")
        for mode, count in result["total_hits"].items():
            print(f"  {mode}: {count}")

        print(f"\n召回率提升:")
        for comparison, improvement in result["recall_improvement_percent"].items():
            print(f"  {comparison}: +{improvement:.1f}%")

        print(f"\n详细报告已保存至: {output_path}")
