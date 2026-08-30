"""LTP 段落特征纯函数测试（§5.3/C1/C2，mock pipeline 输出，不加载模型）"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.linguistic import analyze_paragraph
from src.linguistic.ltp_client import LtpPipelineOutput
from src.utils.text_utils import split_sentences


def _output_for(sentences: list[str]) -> LtpPipelineOutput:
    """手工构造与 LTP pipeline 输出同构的数据"""
    cws: list[list[str]] = []
    pos: list[list[str]] = []
    ner: list[list[tuple[str, str, int, int]]] = []
    dep: list[dict[str, list]] = []
    for sentence in sentences:
        words = list(sentence)
        cws.append(words)
        pos.append(["n"] * len(words))
        heads = [0] + [1] * (len(words) - 1) if len(words) > 1 else [0]
        dep.append({"head": heads, "label": ["HED"] + ["ATT"] * (len(words) - 1)})
        ner.append([])
    return LtpPipelineOutput(cws=cws, pos=pos, ner=ner, dep=dep)


class TestAnalyzeParagraph(unittest.TestCase):
    def test_tokens_with_char_spans_and_pos_groups(self) -> None:
        text = "他叫汤姆去拿外衣。"
        output = _output_for([text])
        result = analyze_paragraph(text, output)
        self.assertEqual(result.ltp_token_count, len(text))
        self.assertEqual(result.tokens[0].text, "他")
        self.assertEqual(result.tokens[0].local_start_char, 0)
        self.assertEqual(result.tokens[0].pos_group, "noun")
        # 词元区间不交叉、覆盖全文
        self.assertEqual(result.tokens[-1].local_end_char, len(text))

    def test_word_length_and_pos_counts_conservation(self) -> None:
        text = "刀光剑影江湖"
        result = analyze_paragraph(text, _output_for([text]))
        self.assertEqual(sum(result.word_length_counts.values()), result.ltp_token_count)
        self.assertEqual(sum(result.pos_counts.values()), result.ltp_token_count)
        self.assertEqual(result.word_length_counts["1"], len(text))

    def test_sentence_patterns_short_medium_long(self) -> None:
        text = "嗯。这是中等长度的句子啊。" + "长" * 35 + "。"
        sentences = split_sentences(text)
        result = analyze_paragraph(text, _output_for(sentences))
        self.assertEqual(result.sentence_pattern_counts["short"], 1)
        self.assertEqual(result.sentence_pattern_counts["medium"], 1)
        self.assertEqual(result.sentence_pattern_counts["long"], 1)

    def test_compound_sentence_detected(self) -> None:
        text = "但是这里有个连词。"
        result = analyze_paragraph(text, _output_for(["但是这里有个连词。"]))
        self.assertEqual(result.sentence_pattern_counts["compound"], 1)

    def test_dependency_depth_tree(self) -> None:
        # 链式依存：1←0(root), 2←1, 3←2 → 深度 0,1,2
        output = LtpPipelineOutput(
            cws=[["a", "b", "c"]],
            pos=[["v", "n", "n"]],
            ner=[[]],
            dep=[{"head": [0, 1, 2], "label": ["HED", "ATT", "ATT"]}],
        )
        result = analyze_paragraph("abc", output)
        self.assertEqual(result.dependency_node_count, 3)
        self.assertEqual(result.dependency_root_count, 1)
        self.assertEqual(result.dependency_depth_sum, 0 + 1 + 2)
        self.assertEqual(result.dependency_depth_max, 2)
        self.assertEqual(result.dependency_relation_counts["HED"], 1)
        self.assertEqual(result.dependency_relation_counts["ATT"], 2)

    def test_dependency_cycle_defensive_depth(self) -> None:
        # 环：1→2→1，防御按深度 1 处理
        output = LtpPipelineOutput(
            cws=[["a", "b"]],
            pos=[["v", "n"]],
            ner=[[]],
            dep=[{"head": [2, 1], "label": ["ATT", "ATT"]}],
        )
        result = analyze_paragraph("ab", output)
        self.assertEqual(result.dependency_node_count, 2)
        self.assertEqual(result.dependency_depth_max, 1)

    def test_entity_candidates_char_spans_from_word_index(self) -> None:
        text = "他叫汤姆去拿外衣。"
        output = LtpPipelineOutput(
            cws=[["他", "叫", "汤姆", "去", "拿", "外衣", "。"]],
            pos=[["r", "v", "nh", "v", "v", "n", "wp"]],
            ner=[[("Nh", "汤姆", 2, 2)]],
            dep=[{"head": [2, 0, 2, 5, 2, 5, 2], "label": ["SBV", "HED", "DBL", "ADV", "VOB", "VOB", "WP"]}],
        )
        result = analyze_paragraph(text, output)
        self.assertEqual(len(result.entities), 1)
        entity = result.entities[0]
        self.assertEqual(entity.surface_text, "汤姆")
        self.assertEqual(entity.raw_entity_type, "Nh")
        self.assertEqual(entity.normalized_entity_type, "person")
        self.assertEqual(text[entity.local_start_char : entity.local_end_char], "汤姆")

    def test_multi_sentence_dep_head_global_coordinate(self) -> None:
        """双句段：第二句 dep head 换算为段落全局索引，不落在第一句区间"""
        text = "他走了。她跑了。"
        output = LtpPipelineOutput(
            cws=[["他", "走", "了", "。"], ["她", "跑", "了", "。"]],
            pos=[["r", "v", "u", "wp"], ["r", "v", "u", "wp"]],
            ner=[[], []],
            dep=[
                {"head": [2, 0, 2, 2], "label": ["SBV", "HED", "RAD", "WP"]},
                # 第二句：head=3 原本是句内索引（指向"跑了"），换算后应为全局索引
                {"head": [2, 0, 2, 2], "label": ["SBV", "HED", "RAD", "WP"]},
            ],
        )
        result = analyze_paragraph(text, output)
        # 第一句：token_index 1-4，head 换算后不变（第一句 sent_token_start=1）
        # 第二句：token_index 5-8，sent_token_start=5，head 换算后 +4
        # 第二句各个弧的 head_index 应 >= 5（第二句范围内）
        arcs = result.dependency_arcs
        # 找出第二句的词元（dependent_index >= 5）
        second_arcs = [a for a in arcs if a.dependent_index >= 5]
        self.assertTrue(len(second_arcs) > 0, "第二句应有依存弧")
        for arc in second_arcs:
            if arc.head_index == 0:
                continue  # ROOT 永远正确
            self.assertGreaterEqual(
                arc.head_index, 5,
                f"dependent_index={arc.dependent_index} 的 head_index={arc.head_index} 应在第二句区间",
            )
        # 全句统计：节点数=8，根数=2（每句一个 ROOT）
        self.assertEqual(result.dependency_node_count, 8)
        self.assertEqual(result.dependency_root_count, 2)

    def test_empty_input_returns_zero_result(self) -> None:
        result = analyze_paragraph("", LtpPipelineOutput(cws=[], pos=[], ner=[], dep=[]))
        self.assertEqual(result.ltp_token_count, 0)
        self.assertEqual(result.sentence_count, 0)
        self.assertEqual(result.word_length_counts, {})


def test_ltp_session_requires_local_model_dir(monkeypatch) -> None:
    """未配置离线模型目录直接报错，不触发 HuggingFace 自动下载回退"""
    import pytest

    from src.config.settings import settings
    from src.linguistic.ltp_client import LtpSession

    ltp_settings = settings.linguistic.ltp
    monkeypatch.setattr(ltp_settings, "model_dir", None, raising=False)
    with pytest.raises(RuntimeError, match="LTP_MODEL_DIR"):
        LtpSession()

    monkeypatch.setattr(ltp_settings, "model_dir", "models/ltp/不存在的目录")
    with pytest.raises(FileNotFoundError, match="不存在的目录"):
        LtpSession()


if __name__ == "__main__":
    unittest.main()