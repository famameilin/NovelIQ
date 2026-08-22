"""
性能基准测试

创建时间: 2026-04-07
任务: 检查性能问题
说明: 测试情绪曲线算法的性能瓶颈

测试场景:
- 否定词检测性能
- 词典匹配性能
- 多类型加权混合性能
- 端到端性能
"""

from __future__ import annotations

import time

from src.lexicons.registry import LexiconRegistry
from src.metrics.emotion_metrics import lexical_sentiment_density
from src.metrics.lexicon_metrics import count_weighted_hits, get_emotion_spans
from src.metrics.negation import is_flipped, load_negation_spec
from src.utils.text_utils import tokenize_words


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


def test_negation_detection_performance():
    """测试否定词检测性能"""
    print("\n" + "=" * 60)
    print("否定词检测性能测试")
    print("=" * 60)

    spec = load_negation_spec()
    test_text = "不是不快乐，而是充满了希望和喜悦"
    emotion_pos = test_text.find("快乐")

    iterations = 10000
    start = time.time()
    for _ in range(iterations):
        is_flipped(test_text, emotion_pos, spec)
    elapsed = time.time() - start

    print(f"否定词数量: {len(spec.hard) + len(spec.modal) + len(spec.double)}")
    print(f"测试次数: {iterations}")
    print(f"总耗时: {elapsed:.3f}秒")
    print(f"平均耗时: {elapsed / iterations * 1000:.3f}毫秒/次")
    print(f"性能: {iterations / elapsed:.0f}次/秒")

    if elapsed / iterations > 0.001:
        print("⚠️  警告: 单次否定词检测耗时超过1毫秒，可能存在性能问题")


def test_lexicon_matching_performance():
    """测试词典匹配性能"""
    print("\n" + "=" * 60)
    print("词典匹配性能测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    pos_terms = _lexicon_set(registry)["pos_terms"]
    neg_terms = _lexicon_set(registry)["neg_terms"]

    print(f"正面词条数: {len(pos_terms)}")
    print(f"负面词条数: {len(neg_terms)}")

    for text_length in [100, 500, 1000, 5000]:
        test_text = generate_test_text(text_length)
        tokens = tokenize_words(test_text)

        start = time.time()
        for _ in range(100):
            count_weighted_hits(test_text, tokens, pos_terms)
        elapsed = time.time() - start

        print(f"\n文本长度: {text_length}字")
        print(f"  单次匹配耗时: {elapsed / 100 * 1000:.2f}毫秒")
        print(f"  性能: {100 / elapsed:.1f}次/秒")

        if elapsed / 100 > 0.1:
            print("  ⚠️  警告: 单次匹配耗时超过100毫秒")


def test_emotion_spans_performance():
    """测试情感词位置获取性能"""
    print("\n" + "=" * 60)
    print("情感词位置获取性能测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    pos_terms = _lexicon_set(registry)["pos_terms"]
    test_text = generate_test_text(1000)
    tokens = tokenize_words(test_text)

    iterations = 100
    start = time.time()
    for _ in range(iterations):
        get_emotion_spans(test_text, tokens, pos_terms.keys())
    elapsed = time.time() - start

    print(f"文本长度: {len(test_text)}字")
    print(f"词条数量: {len(pos_terms)}")
    print(f"测试次数: {iterations}")
    print(f"总耗时: {elapsed:.3f}秒")
    print(f"平均耗时: {elapsed / iterations * 1000:.2f}毫秒/次")


def test_full_emotion_density_performance():
    """测试完整情感密度计算性能"""
    print("\n" + "=" * 60)
    print("完整情感密度计算性能测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]
    neg_terms = lexicon_set["neg_terms"]

    for text_length in [100, 500, 1000, 5000]:
        test_text = generate_test_text(text_length)

        start = time.time()
        for _ in range(10):
            result = lexical_sentiment_density(test_text, pos_terms, neg_terms, enable_negation=True)
        elapsed = time.time() - start

        print(f"\n文本长度: {text_length}字")
        print(f"  单次计算耗时: {elapsed / 10 * 1000:.2f}毫秒")
        print(f"  性能: {10 / elapsed:.1f}次/秒")
        print(f"  结果: pos={result['pos_density']:.4f}, neg={result['neg_density']:.4f}")

        if elapsed / 10 > 1.0:
            print("  ⚠️  警告: 单次计算耗时超过1秒")


def test_weighted_multi_type_performance():
    """测试多类型加权混合性能"""
    print("\n" + "=" * 60)
    print("多类型加权混合性能测试")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    # v3：domain 扩展词表已删，多类型演示基于 registry 单集合
    weighted_lexicons = [_lexicon_set(registry), _lexicon_set(registry)]

    for i, lex in enumerate(weighted_lexicons):
        print(f"类型{i + 1}: pos={len(lex['pos_terms'])}, neg={len(lex['neg_terms'])}")

    test_text = generate_test_text(1000)

    start = time.time()
    for _ in range(10):
        weighted_pos = 0.0
        weighted_neg = 0.0
        for lex_set in weighted_lexicons:
            result = lexical_sentiment_density(test_text, lex_set["pos_terms"], lex_set["neg_terms"])
            weighted_pos += result["pos_density"]
            weighted_neg += result["neg_density"]
    elapsed = time.time() - start

    print(f"\n文本长度: {len(test_text)}字")
    print(f"类型数量: {len(weighted_lexicons)}")
    print(f"单次计算耗时: {elapsed / 10 * 1000:.2f}毫秒")
    print(f"性能: {10 / elapsed:.1f}次/秒")

    if elapsed / 10 > 3.0:
        print("⚠️  警告: 多类型混合计算耗时超过3秒")


def test_end_to_end_performance():
    """测试端到端性能"""
    print("\n" + "=" * 60)
    print("端到端性能测试（模拟真实场景）")
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

    if elapsed > 10:
        print("⚠️  警告: 处理100个Chunk耗时超过10秒")


def profile_hotspot():
    """性能热点分析"""
    print("\n" + "=" * 60)
    print("性能热点分析")
    print("=" * 60)

    registry = LexiconRegistry()
    registry.load()

    lexicon_set = _lexicon_set(registry)
    pos_terms = lexicon_set["pos_terms"]
    neg_terms = lexicon_set["neg_terms"]
    neg_spec = load_negation_spec()

    test_text = generate_test_text(1000)

    print("\n1. 分词性能:")
    start = time.time()
    for _ in range(100):
        tokens = tokenize_words(test_text)
    elapsed = time.time() - start
    print(f"   耗时: {elapsed / 100 * 1000:.2f}毫秒/次")

    print("\n2. 词典匹配性能:")
    tokens = tokenize_words(test_text)
    start = time.time()
    for _ in range(100):
        pos_spans = get_emotion_spans(test_text, tokens, pos_terms.keys())
        neg_spans = get_emotion_spans(test_text, tokens, neg_terms.keys())
    elapsed = time.time() - start
    print(f"   耗时: {elapsed / 100 * 1000:.2f}毫秒/次")
    print(f"   正面词命中: {len(pos_spans)}个")
    print(f"   负面词命中: {len(neg_spans)}个")

    print("\n3. 否定词检测性能:")
    total_negation_checks = 0
    start = time.time()
    for _ in range(10):
        pos_spans = get_emotion_spans(test_text, tokens, pos_terms.keys())
        neg_spans = get_emotion_spans(test_text, tokens, neg_terms.keys())
        for start_pos, _, _ in pos_spans:
            is_flipped(test_text, start_pos, neg_spec)
            total_negation_checks += 1
        for start_pos, _, _ in neg_spans:
            is_flipped(test_text, start_pos, neg_spec)
            total_negation_checks += 1
    elapsed = time.time() - start
    print(f"   耗时: {elapsed / 10 * 1000:.2f}毫秒/次")
    print(f"   否定词检测次数: {total_negation_checks}次")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("情绪曲线算法性能基准测试")
    print("=" * 60)

    test_negation_detection_performance()
    test_lexicon_matching_performance()
    test_emotion_spans_performance()
    test_full_emotion_density_performance()
    test_weighted_multi_type_performance()
    test_end_to_end_performance()
    profile_hotspot()

    print("\n" + "=" * 60)
    print("性能测试完成")
    print("=" * 60)
