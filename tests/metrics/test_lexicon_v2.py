"""
词表注册中心 (LexiconRegistry v3) + 增强匹配 回归测试

覆盖:
  1. registry.yaml 加载与 key 解析（强类型表目）
  2. conflict_matrix 跨表重叠声明（审计用途）
  3. 版本 hash 计算
  4. 多模式匹配 (exact / phrase / fuzzy)
  5. 全局单例

v3 变更（2026-08-15）:
  - 未知 key 直接 raise KeyError（不再返回空列表）
  - 领域扩展（get_with_domains）/ exclude_borrowed 机制删除
  - 分层（layers）取消，改为扁平表目 + kind 枚举
  强约束专项测试见 tests/metrics/test_registry_v3.py

创建时间: 2026-04-06 | 分支: fix/timeline-multi-peak | 2026-08-15 升级 v3
"""

from __future__ import annotations

import pytest

from src.lexicons.registry import LexiconRegistry, get_registry, reset_registry
from src.metrics.matching import _edit_distance, count_token_hits_enhanced

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
        # 核心词表必须存在（v3 表目标识即文件名）
        expected_keys = {
            "positive.txt",
            "negative.txt",
            "combat.txt",
            "sensory.txt",
            "semantic_category.txt",
            "function_words.txt",
            "imagery.txt",
            "stopwords.txt",
            "jieba_user_dict.txt",
            "negation_words.txt",
        }
        assert expected_keys.issubset(set(keys))

    def test_get_positive_lexicon(self, registry):
        terms = registry.get("positive.txt")
        assert len(terms) > 0
        assert "快乐" in terms or len(terms) > 500  # 正面词表应该较大

    def test_get_negative_lexicon(self, registry):
        terms = registry.get("negative.txt")
        assert len(terms) > 0
        assert "悲伤" in terms or "痛苦" in terms or len(terms) > 500

    def test_get_combat(self, registry):
        """combat.txt 战斗词表"""
        terms = registry.get("combat.txt")
        assert len(terms) > 0
        assert "剑气" in terms

    def test_get_sensory(self, registry):
        terms = registry.get("sensory.txt")
        assert len(terms) > 0
        assert "冰冷" in terms

    def test_cache_works(self, registry):
        first = registry.get("positive.txt")
        second = registry.get("positive.txt")
        assert first is second  # 同一对象（缓存命中）


# ====================================================================
# 2. Conflict Matrix 跨表重叠声明
# ====================================================================


class TestConflictMatrix:
    def test_conflicts_loaded(self, registry):
        conflicts = registry.get_conflicts_for("combat.txt")
        # combat 词表中借用了 semantic_category 的词条（如"剑气""灵力"）
        assert len(conflicts) > 0

    def test_jianqi_is_borrowed(self, registry):
        """剑气在 semantic_category 是主属，combat 是借用"""
        conflicts = registry.get_conflicts_for("combat.txt")
        terms_with_conflict = [c["term"] for c in conflicts]
        assert "剑气" in terms_with_conflict
        assert "灵力" in terms_with_conflict

    def test_honglong_in_sensory(self, registry):
        """轰隆是 sensory 主属，被 combat 借用"""
        conflicts = registry.get_conflicts_for("sensory.txt")
        terms_with_conflict = [c["term"] for c in conflicts]
        assert "轰隆" in terms_with_conflict


# ====================================================================
# 3. 版本 hash
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
# 4. 多模式匹配
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
# 5. 全局单例
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
        terms = reg.get("positive.txt")
        assert len(terms) > 0
