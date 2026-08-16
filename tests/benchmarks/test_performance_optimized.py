"""
性能基准测试 - 优化版本对比

创建时间: 2026-04-07
任务: 性能优化验证
说明: 对比优化前后的性能差异

测试场景:
- Aho-Corasick优化 vs 暴力匹配
- 多类型词典合并优化
- 端到端性能对比
"""

from __future__ import annotations

import time

from src.lexicons.registry import LexiconRegistry
from src.metrics.emotion_metrics import lexical_sentiment_density
from src.metrics.lexicon_metrics import (
    build_automaton,
    get_emotion_spans,
    get_emotion_spans_fast,
)
from src.metrics.text_utils import tokenize_words


def _lexicon_set(registry: LexiconRegistry) -> dict[str, dict[str, int]]:
    """v3：registry 直接组装加权词表集合（get_weighted_lexicon_set 已删除）"""
    return {
        "pos_terms": registry.get_weighted("positive.txt"),
        "neg_terms": registry.get_weighted("negative.txt"),
        "fight_terms": dict.fromkeys(registry.get("combat.txt"), 1.0),
    }


def generate_test_text(length: int = 1000) -> str:
    """生成测试文本"""
    base_text = """
    这是一个快乐的故事，主角在修炼过程中遇到了很多困难。
    他不快乐地叹了口气，但是并没有放弃。
    心花怒放的时刻终于来了，他突破了瓶颈。
    不是不快乐，而是充满了希望。
    绝杀的招式展现出了强大的威力，血战之后终于取得了胜利。
    """ * (length // 100 + 1)
    return base_text[:length]


def test_aho_corasick_optimization():
    """测试Aho-Corasick优化效果"""
    print("\n" + "=" * 60)
    print("Aho-Corasick优化效果测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]

    test_text = generate_test_text(1000)
    tokens = tokenize_words(test_text)

    print(f"文本长度: {len(test_text)}字")
    print(f"词条数量: {len(pos_terms)}")

    print("\n1. 暴力匹配（原版）:")
    start = time.time()
    for _ in range(100):
        get_emotion_spans(test_text, tokens, pos_terms.keys())
    elapsed_old = time.time() - start
    print(f"   耗时: {elapsed_old / 100 * 1000:.2f}毫秒/次")

    print("\n2. Aho-Corasick优化:")
    automaton = build_automaton(pos_terms.keys())
    start = time.time()
    for _ in range(100):
        get_emotion_spans_fast(test_text, automaton, tokens)
    elapsed_new = time.time() - start
    print(f"   耗时: {elapsed_new / 100 * 1000:.2f}毫秒/次")

    # 词表收敛后匹配耗时可能小到计时器归零，给分母加下界避免除零
    speedup = elapsed_old / max(elapsed_new, 1e-9)
    print(f"\n✅ 性能提升: {speedup:.2f}倍")
    print(f"   时间节省: {(elapsed_old - elapsed_new) / 100 * 1000:.2f}毫秒/次")


def test_multi_type_merge_optimization():
    """测试多类型词典合并优化效果"""
    print("\n" + "=" * 60)
    print("多类型词典合并优化效果测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    # v3：domain 扩展词表已删，合并演示基于 registry 单集合
    weighted_lexicons = [_lexicon_set(registry), _lexicon_set(registry)]

    for i, lex in enumerate(weighted_lexicons):
        print(f"类型{i + 1}: pos={len(lex['pos_terms'])}, neg={len(lex['neg_terms'])}")

    chunk_texts = [(i, generate_test_text(500)) for i in range(10)]

    print(f"\nChunk数量: {len(chunk_texts)}")
    print("每个Chunk长度: 500字")

    print("\n1. 优化版（Aho-Corasick 单遍匹配）:")
    merged_pos: dict[str, float] = {}
    merged_neg: dict[str, float] = {}
    for lex in weighted_lexicons:
        merged_pos.update(lex["pos_terms"])
        merged_neg.update(lex["neg_terms"])
    automaton = build_automaton(merged_pos.keys())
    start = time.time()
    for _ in range(10):
        for _chunk_id, text in chunk_texts:
            get_emotion_spans_fast(text, automaton)
    elapsed_new = time.time() - start
    print(f"   耗时: {elapsed_new / 10 * 1000:.2f}毫秒/次")


def test_end_to_end_optimization():
    """测试端到端优化效果"""
    print("\n" + "=" * 60)
    print("端到端优化效果测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]
    neg_terms = lexicon_set["neg_terms"]

    chunk_count = 100
    chunk_length = 500

    print(f"Chunk数量: {chunk_count}")
    print(f"每个Chunk长度: {chunk_length}字")
    print(f"总文本长度: {chunk_count * chunk_length}字")

    chunk_texts = [(i, generate_test_text(chunk_length)) for i in range(chunk_count)]

    start = time.time()
    for _chunk_id, text in chunk_texts:
        lexical_sentiment_density(text, pos_terms, neg_terms)
    elapsed = time.time() - start

    print(f"\n总耗时: {elapsed:.3f}秒")
    print(f"平均每个Chunk: {elapsed / chunk_count * 1000:.2f}毫秒")
    print(f"处理速度: {chunk_count * chunk_length / elapsed:.0f}字/秒")

    print("\n✅ 对比优化前:")
    print("   优化前: ~0.394秒")
    print(f"   优化后: {elapsed:.3f}秒")
    if elapsed < 0.394:
        speedup = 0.394 / elapsed
        print(f"   性能提升: {speedup:.2f}倍")


def test_different_text_lengths():
    """测试不同文本长度的性能"""
    print("\n" + "=" * 60)
    print("不同文本长度性能测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]

    automaton = build_automaton(pos_terms.keys())

    for text_length in [100, 500, 1000, 5000, 10000]:
        test_text = generate_test_text(text_length)
        tokens = tokenize_words(test_text)

        print(f"\n文本长度: {text_length}字")

        print("  暴力匹配:", end=" ")
        start = time.time()
        for _ in range(10):
            get_emotion_spans(test_text, tokens, pos_terms.keys())
        elapsed_old = time.time() - start
        print(f"{elapsed_old / 10 * 1000:.2f}毫秒")

        print("  Aho-Corasick:", end=" ")
        start = time.time()
        for _ in range(10):
            get_emotion_spans_fast(test_text, automaton, tokens)
        elapsed_new = time.time() - start
        print(f"{elapsed_new / 10 * 1000:.2f}毫秒")

        # 词表收敛后匹配耗时可能小到计时器归零，给分母加下界避免除零
        speedup = elapsed_old / max(elapsed_new, 1e-9)
        print(f"  性能提升: {speedup:.2f}倍")


def test_automaton_reuse():
    """测试自动机复用效果"""
    print("\n" + "=" * 60)
    print("自动机构建与复用测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]

    print(f"词条数量: {len(pos_terms)}")

    print("\n1. 构建自动机:")
    start = time.time()
    automaton = build_automaton(pos_terms.keys())
    elapsed_build = time.time() - start
    print(f"   耗时: {elapsed_build * 1000:.2f}毫秒")

    print("\n2. 复用自动机（100次匹配）:")
    test_text = generate_test_text(1000)
    start = time.time()
    for _ in range(100):
        get_emotion_spans_fast(test_text, automaton)
    elapsed_reuse = time.time() - start
    print(f"   耗时: {elapsed_reuse / 100 * 1000:.2f}毫秒/次")

    print("\n✅ 结论: 自动机构建一次，可重复使用")
    print(f"   构建开销: {elapsed_build * 1000:.2f}毫秒")
    print(f"   单次匹配: {elapsed_reuse / 100 * 1000:.2f}毫秒")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("性能优化验证测试")
    print("=" * 60)

    test_aho_corasick_optimization()
    test_multi_type_merge_optimization()
    test_end_to_end_optimization()
    test_different_text_lengths()
    test_automaton_reuse()

    print("\n" + "=" * 60)
    print("性能优化验证完成")
    print("=" * 60)
