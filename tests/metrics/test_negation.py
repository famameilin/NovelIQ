"""
共享否定层测试（src/metrics/negation，docs/词表体系重设计-修订版实施计划.md M5）

覆盖：
  1. 分类加载：hard/modal/double 分组解析
  2. longest-match 去重：复合词优先，非重叠 span 单词只计一次
  3. 句边界：跨句否定不翻转
  4. 最近距离约束：否定与情绪词之间 >1 token 不翻转
  5. modal 不翻转（未必/莫非/难以…）
  6. double 双重否定 parity 抵消（不得不…）
  7. 真实误判回归（2026-08 审计 5 例）
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.metrics.negation import (
    NegationSpec,
    find_negation_spans,
    is_flipped,
    load_negation_spec,
)

_POS_EMOTION = "快乐"
_NEG_EMOTION = "痛苦"


@pytest.fixture(scope="module")
def spec() -> NegationSpec:
    return load_negation_spec()


def _flipped(text: str, emotion: str, neg_spec: NegationSpec) -> bool:
    """文本中首个情绪词是否被否定翻转"""
    pos = text.find(emotion)
    assert pos >= 0, f"情绪词 {emotion} 未出现在文本中"
    return is_flipped(text, pos, neg_spec)


# ====================================================================
# 1. 分类加载
# ====================================================================


class TestSpecLoading:
    def test_groups_loaded(self, spec: NegationSpec) -> None:
        assert "不" in spec.hard
        assert "没有" in spec.hard
        assert "不得不" in spec.double
        assert "未必" in spec.modal
        assert "难以" in spec.modal

    def test_misleading_single_chars_removed(self, spec: NegationSpec) -> None:
        """误伤单字已剔除：别/莫/非/无（别人/特别/莫名/非常/无声…）"""
        assert "别" not in spec.hard
        assert "莫" not in spec.hard
        assert "非" not in spec.hard
        assert "无" not in spec.hard

    def test_longest_match_priority(self, spec: NegationSpec) -> None:
        """复合词（并没有）优先于其子串（并不/没有/没/不）"""
        spans = find_negation_spans("他并没有放弃", spec)
        words = [s.word for s in spans]
        assert "并没有" in words
        # 并没有 命中后，子串不重复计
        assert "不" not in words and "没有" not in words and "没" not in words

    def test_custom_file(self, tmp_path: Path) -> None:
        p = tmp_path / "neg.txt"
        p.write_text(
            "# ===== hard =====\n不\n没\n# ===== modal =====\n未必\n# ===== double =====\n不得不\n",
            encoding="utf-8",
        )
        s = load_negation_spec(p)
        assert s.hard == frozenset({"不", "没"})
        assert s.modal == frozenset({"未必"})
        assert s.double == frozenset({"不得不"})


# ====================================================================
# 2. 翻转语义
# ====================================================================


class TestFlipSemantics:
    def test_single_negation_flips(self, spec: NegationSpec) -> None:
        assert _flipped("他不快乐", _POS_EMOTION, spec) is True

    def test_no_negation_not_flipped(self, spec: NegationSpec) -> None:
        assert _flipped("他很快乐", _POS_EMOTION, spec) is False

    def test_double_negation_restores(self, spec: NegationSpec) -> None:
        """双重否定还原："不是不快乐" 不翻转"""
        assert _flipped("他不是不快乐", _POS_EMOTION, spec) is False

    def test_double_group_restores(self, spec: NegationSpec) -> None:
        """double 组（不得不）计 2 次，parity 抵消"""
        assert _flipped("他不得不快乐地接受了", _POS_EMOTION, spec) is False

    def test_modal_does_not_flip(self, spec: NegationSpec) -> None:
        """modal（未必/难以）不翻转极性"""
        assert _flipped("他未必快乐", _POS_EMOTION, spec) is False
        assert _flipped("他难以快乐", _POS_EMOTION, spec) is False

    def test_negative_term_flips_to_positive(self, spec: NegationSpec) -> None:
        """否定翻转同样作用于负面词："不痛苦" 计入正向"""
        assert _flipped("他不痛苦", _NEG_EMOTION, spec) is True

    def test_cross_sentence_not_flipped(self, spec: NegationSpec) -> None:
        """句边界：跨句否定不翻转"""
        assert _flipped("他没有来。他很快乐", _POS_EMOTION, spec) is False

    def test_emotion_at_start_not_flipped(self, spec: NegationSpec) -> None:
        assert _flipped("快乐地笑了", _POS_EMOTION, spec) is False


# ====================================================================
# 3. 真实误判回归（2026-08 审计 5 例）
# ====================================================================


class TestAuditRegressions:
    def test_bu_mie_de_zui_hou_xi_wang(self, spec: NegationSpec) -> None:
        """"不灭的最后希望"：否定与情绪词间隔过远，不翻转"""
        assert _flipped("不灭的最后希望", "希望", spec) is False

    def test_mei_chajue_de_xingfen(self, spec: NegationSpec) -> None:
        """"没察觉的兴奋"：间隔"察觉的"超 1 token，不翻转"""
        assert _flipped("没察觉的兴奋", "兴奋", spec) is False

    def test_bing_meiyou_huanhu_que_yue(self, spec: NegationSpec) -> None:
        """"并没有…欢呼雀跃"：longest-match 单计，正确翻转"""
        assert _flipped("他并没有为此欢呼雀跃", "欢呼雀跃", spec) is True

    def test_kan_dou_mei_kan_fa_dou(self, spec: NegationSpec) -> None:
        """"看都没看跪在地上发抖"：否定距"发抖"过远，不翻转"""
        assert _flipped("看都没看跪在地上发抖", "发抖", spec) is False

    def test_corpus_clause_initial_scope(self, spec: NegationSpec) -> None:
        """语料实测（重明传）：小句首"并没有"管辖整个小句，跨 3 token 仍翻转"""
        assert (
            _flipped(
                "猴子、柱子和算盘一落地，并没有像往常一样欢呼雀跃，而是扑通几声跪下了。",
                "欢呼雀跃",
                spec,
            )
            is True
        )

    def test_clause_boundary_stops_scope(self, spec: NegationSpec) -> None:
        """小句首否定但情绪词在下一个分句：分句界阻断，不翻转"""
        assert _flipped("并没有，他欢呼雀跃", "欢呼雀跃", spec) is False

    def test_shebude_scope_flips(self, spec: NegationSpec) -> None:
        """语料实例（重明传）："舍不得让你受委屈"——"舍不得"辖制其后动词短语，
        scope 类否定不适用距离约束，正确翻转"""
        assert _flipped("老天爷肯定舍不得让你受委屈的", "委屈", spec) is True

    def test_shebude_attributive_not_flipped(self, spec: NegationSpec) -> None:
        """scope 类否定的"的"（定语）阻断："舍不得的快乐"不翻转"""
        assert _flipped("那份舍不得的快乐", "快乐", spec) is False

    def test_shebude_clause_boundary_not_flipped(self, spec: NegationSpec) -> None:
        """scope 类否定跨分句界阻断：舍不得在上一分句，不辖制下一分句情绪词"""
        assert _flipped("他舍不得走，却很开心", "开心", spec) is False

    def test_shebude_double_negation_parity(self, spec: NegationSpec) -> None:
        """scope 与 hard 叠加计 2：奇偶抵消，不翻转"""
        assert _flipped("他舍不得不开心", "开心", spec) is False

    def test_meiyou_duo_not_flipped(self, spec: NegationSpec) -> None:
        """语料实测（重明传）："算盘没有躲"否定辖"躲"，不辖后文"绝望"——不翻转"""
        assert _flipped("算盘没有躲，眼神中全是深深的悔恨与绝望", "绝望", spec) is False

    def test_henduo_guanyong_bingmeiyou(self, spec: NegationSpec) -> None:
        """"并没有"入表后单计一次（不再与"并不"+"没有"双计）"""
        spans = find_negation_spans("他并没有", spec)
        hard_hits = [s for s in spans if s.kind == "hard"]
        assert [s.word for s in hard_hits] == ["并没有"]
