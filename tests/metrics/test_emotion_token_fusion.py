"""
单字情绪词融合修复回归（2026-08-16，分词层修复）

根因：jieba 将"副词+爽/慌"与"爽/慌+得/到"融合为单 token，token 对齐匹配
打不中单字表词。修复在 Tokenizer 加载用户词典后 del_word 移除融合词路由
（基础词典词）并注册 force_split（HMM 模型词），详见 src/preprocess/tokenize.py。
爱 类融合刻意不修（习惯性偏好漂移：最爱说/太爱装）。
"""

from __future__ import annotations

from src.metrics.lexicon_metrics import get_emotion_spans
from src.metrics.negation import is_flipped, load_negation_spec
from src.preprocess.tokenize import tokenize


def _spans(text: str, terms: set[str]) -> list[str]:
    return [t for _s, _e, t in get_emotion_spans(text, tokenize(text), terms)]


class TestFusionSplits:
    def test_adverb_fusion_splits(self) -> None:
        """副词融合切开：很爽/最爽的一天/太爽了/挺爽的"""
        assert _spans("心里很爽", {"爽"}) == ["爽"]
        assert _spans("最爽的一天", {"爽"}) == ["爽"]
        assert _spans("太爽了", {"爽"}) == ["爽"]
        assert _spans("挺爽的", {"爽"}) == ["爽"]

    def test_de_dao_suffix_splits(self) -> None:
        """得/到 后缀融合切开（HMM 词 force_split）"""
        assert _spans("爽得飞起", {"爽"}) == ["爽"]
        assert _spans("爽到爆", {"爽"}) == ["爽"]

    def test_huang_fusion_splits(self) -> None:
        assert _spans("他太慌了", {"慌"}) == ["慌"]

    def test_shuangbao_word(self) -> None:
        """爽爆了 作为独立词条收录"""
        assert _spans("爽爆了", {"爽爆"}) == ["爽爆"]

    def test_negation_flip_after_split(self) -> None:
        """ "不是很爽"：切开后 爽 与"不是"相邻，正确翻转"""
        spec = load_negation_spec()
        toks = tokenize("不是很爽")
        spans = get_emotion_spans("不是很爽", toks, {"爽"})
        assert spans == [(3, 4, "爽")]
        assert is_flipped("不是很爽", 3, spec) is True


class TestFusionNoFalsePositives:
    def test_compounds_not_split(self) -> None:
        """误伤防护：含 爽/慌/爱 的复合词不被切开、不命中单字表词"""
        for text in ("清爽", "飒爽英姿", "爽快", "爱情", "恋爱", "可爱", "慌张", "惊慌", "荒唐"):
            terms = {"爽"} if "爽" in text else {"慌"} if "慌" in text else {"爱"}
            assert _spans(text, terms) == [], f"{text} 误命中"

    def test_fused_ai_stays_fused(self) -> None:
        """爱 类融合刻意不修：最爱说（习惯用法）不产生情绪命中"""
        assert _spans("最爱说的一句玩笑话", {"爱"}) == []
