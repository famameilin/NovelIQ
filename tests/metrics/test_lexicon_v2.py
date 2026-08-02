"""
词表注册中心 (LexiconRegistry v2) + 增强匹配 回归测试

覆盖:
  1. registry.yaml 加载与 key 解析
  2. conflict_matrix 跨表重叠检测
  3. 领域扩展词表叠加 (get_with_domains)
  4. exclude_borrowed 排除借用词
  5. 版本 hash 计算
  6. 多模式匹配 (exact / phrase / fuzzy)
  7. tension_composite v2 加权模型

创建时间: 2026-04-06 | 分支: fix/timeline-multi-peak
"""

from __future__ import annotations

import pytest

from src.lexicons.registry import LexiconRegistry, get_registry, reset_registry
from src.metrics.matching import _edit_distance, count_token_hits_enhanced
from src.workflows.aggregate import TENSION_COMPOSITE_WEIGHTS, _compute_tension_composite

# ====================================================================
# 测试夹具
# ====================================================================


@pytest.fixture()
def registry() -> LexiconRegistry:
    """使用项目真实 data/lexicons 目录创建 Registry"""
    reg = LexiconRegistry()  # 默认 base_dir=data/lexicons
    reg.load()
    return reg


# ====================================================================
# 1. Registry 加载与 key 解析
# ====================================================================


class TestLexiconRegistryLoad:
    def test_loads_successfully(self, registry):
        assert registry.is_loaded is True
        assert len(registry.list_all_keys()) > 0

    def test_lists_all_registered_keys(self, registry):
        keys = registry.list_all_keys()
        # 核心词表必须存在
        expected_keys = {
            "emotion.positive",
            "emotion.negative",
            "tension.action_terms",
            "style.sensory_5sense",
            "style.semantic_10cat",
            "culture.imagery",
            "culture.idioms",
            "auxiliary.stopwords",
        }
        assert expected_keys.issubset(set(keys))

    def test_get_positive_lexicon(self, registry):
        terms = registry.get("emotion.positive")
        assert len(terms) > 0
        assert "快乐" in terms or len(terms) > 500  # 正面词表应该较大

    def test_get_negative_lexicon(self, registry):
        terms = registry.get("emotion.negative")
        assert len(terms) > 0
        assert "悲伤" in terms or "痛苦" in terms or len(terms) > 500

    def test_get_combat_as_action_terms(self, registry):
        """combat.txt 通过 tension.action_terms 访问"""
        terms = registry.get("tension.action_terms")
        assert len(terms) > 0
        assert "剑气" in terms

    def test_get_sensory(self, registry):
        terms = registry.get("style.sensory_5sense")
        assert len(terms) > 0
        assert "冰冷" in terms

    def test_unknown_key_returns_empty(self, registry):
        terms = registry.get("nonexistent.layer")
        assert terms == []

    def test_cache_works(self, registry):
        first = registry.get("emotion.positive")
        second = registry.get("emotion.positive")
        assert first is second  # 同一对象（缓存命中）


# ====================================================================
# 2. Conflict Matrix 跨表重叠检测
# ====================================================================


class TestConflictMatrix:
    def test_conflicts_loaded(self, registry):
        conflicts = registry.get_conflicts_for("tension.action_terms")
        # combat 词表中借用了 semantic_category 的词条（如"剑气""灵力"）
        assert len(conflicts) > 0

    def test_jianqi_is_borrowed(self, registry):
        """剑气在 semantic_category 是主属，action_terms 是借用"""
        conflicts = registry.get_conflicts_for("tension.action_terms")
        terms_with_conflict = [c["term"] for c in conflicts]
        assert "剑气" in terms_with_conflict
        assert "灵力" in terms_with_conflict

    def test_honglong_in_sensory(self, registry):
        """轰隆是 sensory 主属，被 action_terms 借用"""
        conflicts = registry.get_conflicts_for("style.sensory_5sense")
        terms_with_conflict = [c["term"] for c in conflicts]
        assert "轰隆" in terms_with_conflict


# ====================================================================
# 3. exclude_borrowed 排除借用词
# ====================================================================


class TestExcludeBorrowed:
    def test_exclude_reduces_combat_count(self, registry):
        """排除借用词后，action_terms 应该减少"""
        all_terms = registry.get("tension.action_terms", exclude_borrowed=False)
        primary_only = registry.get("tension.action_terms", exclude_borrowed=True)
        # 借用词被排除后数量应 ≤ 全量
        assert len(primary_only) <= len(all_terms)

    def test_jianqi_excluded_from_action_terms(self, registry):
        """剑气从 action_terms 中被排除"""
        primary_only = registry.get("tension.action_terms", exclude_borrowed=True)
        # 剑气的 primary 是 style.semantic_10cat，所以应该在 action_terms 的排除列表中
        if "剑气" in registry.get("tension.action_terms"):
            # 只有当原始包含时才验证排除
            assert "剑气" not in primary_only


# ====================================================================
# 4. 领域扩展词表
# ====================================================================


class TestDomainExtension:
    def test_xianxia_domain_exists(self, registry):
        xianxia_neg = registry._load_domain_lexicon("xianxia_negative")
        xianxia_pos = registry._load_domain_lexicon("xianxia_positive")
        assert len(xianxia_neg) > 0
        assert len(xianxia_pos) > 0

    def test_xianxia_negative_has_specific_terms(self, registry):
        """修仙负面术语应包含特定词条"""
        terms = registry._load_domain_lexicon("xianxia_negative")
        assert "渡劫失败" in terms
        assert "走火入魔" in terms
        assert "道心破碎" in terms

    def test_get_with_domains_extends_base(self, registry):
        """领域扩展应在基础词表上做增量叠加"""
        base = registry.get("emotion.negative")
        extended = registry.get_with_domains("emotion.negative", ["xianxia_negative"])
        assert len(extended) >= len(base)

    def test_domain_deduplicates(self, registry):
        """domain 扩展应去重"""
        extended = registry.get_with_domains("emotion.negative", ["xianxia_negative"])
        assert len(extended) == len(set(extended))

    def test_nonexistent_domain_graceful(self, registry):
        """不存在的 domain 不应报错，只跳过"""
        result = registry.get_with_domains("emotion.positive", ["nonexistent_domain_xyz"])
        # 应该返回基础词表
        base = registry.get("emotion.positive")
        assert len(result) == len(base)

    def test_multiple_domains(self, registry):
        """支持多个 domain 同时加载"""
        extended = registry.get_with_domains(
            "emotion.negative",
            ["xianxia_negative", "power_struggle"],
        )
        base = registry.get("emotion.negative")
        assert len(extended) >= len(base)


# ====================================================================
# 5. 版本 hash
# ====================================================================


class TestVersionHash:
    def test_hash_is_string(self, registry):
        h = registry.version_hash()
        assert isinstance(h, str)
        assert len(h) == 16  # 只取 hexdigest[:16]

    def test_hash_is_deterministic(self, registry):
        h1 = registry.version_hash()
        h2 = registry.version_hash()
        assert h1 == h2


# ====================================================================
# 6. 多模式匹配
# ====================================================================


class TestEnhancedMatching:
    @pytest.fixture()
    def sample_text_tokens(self):
        text = "他心中一阵刺痛，冷笑一声。"
        tokens = ["他", "心中", "一阵", "刺痛", "冷", "笑", "一", "声"]
        return text, tokens

    def test_phrase_mode_matches_tokens(self):
        """phrase 模式匹配 token 级别"""
        text = "他心中一阵刺痛冰冷眼神"
        tokens = ["他", "心中", "一阵", "刺痛", "冰冷", "眼神"]
        terms = ["刺痛", "冰冷", "眼神"]
        phrase_count = count_token_hits_enhanced(text, tokens, terms, mode="phrase")
        assert phrase_count == 3

    def test_phrase_mode_catches_unsegmented(self):
        """phrase 模式能匹配未登录词如'冷笑'"""
        text = "她冷笑一声"
        tokens = ["她", "冷", "笑", "一", "声"]
        terms = ["冷笑", "刺痛", "冰冷"]
        phrase_count = count_token_hits_enhanced(text, tokens, terms, mode="phrase")
        assert phrase_count >= 1

    def test_fuzzy_mode_catches_variants(self):
        """fuzzy 模式能容忍编辑距离"""
        text = "他挥出剑罡"
        tokens = ["他", "挥出", "剑罡"]
        terms = ["剑气", "剑意", "剑光"]
        fuzzy_count = count_token_hits_enhanced(text, tokens, terms, mode="fuzzy")
        phrase_count = count_token_hits_enhanced(text, tokens, terms, mode="phrase")
        assert fuzzy_count >= phrase_count

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown match mode"):
            count_token_hits_enhanced("test", ["a", "b"], ["x"], mode="invalid")


class TestEditDistance:
    def test_identical_strings(self):
        assert _edit_distance("abc", "abc") == 0

    def test_one_edit(self):
        assert _edit_distance("abc", "abd") == 1

    def test_completely_different(self):
        assert _edit_distance("abc", "xyz") == 3

    def test_empty_string(self):
        assert _edit_distance("", "abc") == 3
        assert _edit_distance("abc", "") == 3

    def test_chinese_chars(self):
        assert _edit_distance("剑气", "剑罡") == 1
        assert _edit_distance("刺痛", "刺痛") == 0


# ====================================================================
# 7. tension_composite v2 加权模型
# ====================================================================


class TestTensionCompositeV2:
    def _make_signals(self) -> list[dict]:
        """构造测试用的张力信号数据"""
        return [
            {
                "emotion_intensity": 0.001,
                "dialogue_ratio": 0.2,
                "sent_len_std": 8,
                "event_score": 0.2,
                "cliffhanger_score": 0,
            },  # 低张力 chunk
            {
                "emotion_intensity": 0.005,
                "dialogue_ratio": 0.35,
                "sent_len_std": 15,
                "event_score": 0.6,
                "cliffhanger_score": 0,
            },  # 中等事件
            {
                "emotion_intensity": 0.01,
                "dialogue_ratio": 0.45,
                "sent_len_std": 25,
                "event_score": 0.8,
                "cliffhanger_score": 1,
            },  # 高潮 chunk
            {
                "emotion_intensity": 0.002,
                "dialogue_ratio": 0.18,
                "sent_len_std": 33,
                "event_score": 0.2,
                "cliffhanger_score": 0,
            },  # 高 sent_len_std 但低语义
        ]

    def test_weights_are_defined(self):
        expected_keys = {"emotion_intensity", "dialogue_ratio", "sent_len_std", "event_score", "cliffhanger_score"}
        assert set(TENSION_COMPOSITE_WEIGHTS.keys()) == expected_keys

    def test_event_score_has_highest_weight(self):
        """LLM 语义判断权重最高"""
        assert TENSION_COMPOSITE_WEIGHTS["event_score"] == max(TENSION_COMPOSITE_WEIGHTS.values())

    def test_sent_len_std_has_lowest_weight(self):
        """句长标准差权重最低"""
        assert TENSION_COMPOSITE_WEIGHTS["sent_len_std"] == min(TENSION_COMPOSITE_WEIGHTS.values())

    def test_output_range_normalized(self):
        composites = _compute_tension_composite(self._make_signals())
        for c in composites:
            assert 0.0 <= c <= 1.0

    def test_high_event_chunk_scores_higher(self):
        """高 event_score 的 chunk 应获得更高 composite"""
        composites = _compute_tension_composite(self._make_signals())
        # index=2 有 event=0.8 + cliffhanger=1，应该是峰值
        peak_idx = max(range(len(composites)), key=lambda i: composites[i])
        assert peak_idx == 2

    def test_sent_len_std_no_longer_dominates(self):
        """sent_len_std 最大(index=3)但语义弱 → composite 不应是最高"""
        composites = _compute_tension_composite(self._make_signals())
        # index=3 的 sent_len_std=33 是最大值
        # 但 event_score=0.2 很低，加权后不应主导
        assert composites[3] < composites[2]

    def test_empty_input(self):
        assert _compute_tension_composite([]) == []

    def test_single_signal(self):
        signals = [
            {
                "emotion_intensity": 0.5,
                "dialogue_ratio": 0.5,
                "sent_len_std": 10,
                "event_score": 0.5,
                "cliffhanger_score": 0.5,
            }
        ]
        result = _compute_tension_composite(signals)
        assert len(result) == 1
        # 单信号归一化后所有维度都是 0 或 1（min=max 时归一化为 0）
        # 所以结果取决于 min==max 的处理 → normalized=0
        assert result[0] == 0.0


# ====================================================================
# 8. 全局单例管理
# ====================================================================


class TestGlobalSingleton:
    def test_reset_clears_singleton(self):
        reset_registry()
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2
        reset_registry()
        r3 = get_registry()
        # 重置后应该是新实例
        assert r3 is not r1

    def test_lazy_load(self):
        reset_registry()
        reg = get_registry()
        # 未调用 load() 前 is_loaded 为 False
        assert reg.is_loaded is False
        # 调用 get 触发延迟加载
        terms = reg.get("emotion.positive")
        assert len(terms) > 0
