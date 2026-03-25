"""
创建时间: 2026-03-16
创建者: TraeAI
任务: fix-disambiguation-three-phase
说明: 测试变体反查表功能，验证变体生成逻辑和揭示句匹配功能
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.workflows.annotate_helpers.sentence import _get_name_variants, _build_sentence_pool


class TestGetNameVariants(unittest.TestCase):
    """
    创建时间: 2026-03-16
    创建者: TraeAI
    任务: fix-disambiguation-three-phase
    说明: 测试 _get_name_variants 函数的变体生成逻辑
    """

    def test_three_char_name_without_short_conflict(self) -> None:
        """
        三字名字，短形式不是独立候选，应展开
        贺重明, {"贺重明", "伯安"} → ["贺重明", "重明"]
        """
        name_set = {"贺重明", "伯安"}
        result = _get_name_variants("贺重明", name_set)
        self.assertEqual(result, ["贺重明", "重明"])

    def test_three_char_name_with_short_conflict(self) -> None:
        """
        三字名字，短形式已是独立候选，不展开
        贺重明, {"贺重明", "重明", "伯安"} → ["贺重明"]
        """
        name_set = {"贺重明", "重明", "伯安"}
        result = _get_name_variants("贺重明", name_set)
        self.assertEqual(result, ["贺重明"])

    def test_two_char_name(self) -> None:
        """
        两字名字，不生成短形式
        伯安, {"伯安"} → ["伯安"]
        """
        name_set = {"伯安"}
        result = _get_name_variants("伯安", name_set)
        self.assertEqual(result, ["伯安"])

    def test_single_char_name(self) -> None:
        """
        单字名字，不生成短形式
        """
        name_set = {"明"}
        result = _get_name_variants("明", name_set)
        self.assertEqual(result, ["明"])

    def test_four_char_name(self) -> None:
        """
        四字名字，生成去掉第一个字的短形式
        欧阳重明, {"欧阳重明"} → ["欧阳重明", "阳重明"]
        """
        name_set = {"欧阳重明"}
        result = _get_name_variants("欧阳重明", name_set)
        self.assertEqual(result, ["欧阳重明", "阳重明"])

    def test_four_char_name_with_short_conflict(self) -> None:
        """
        四字名字，短形式已是独立候选，不展开
        """
        name_set = {"欧阳重明", "阳重明"}
        result = _get_name_variants("欧阳重明", name_set)
        self.assertEqual(result, ["欧阳重明"])


class TestBuildSentencePoolWithVariants(unittest.TestCase):
    """
    创建时间: 2026-03-16
    创建者: TraeAI
    任务: fix-disambiguation-three-phase
    说明: 测试 _build_sentence_pool 函数的变体匹配功能
    """

    def test_variant_matching_reveals_sentence(self) -> None:
        """
        揭示句包含短形式，应匹配到完整候选名
        例如：句子包含"重明"（贺重明的短形式），应归入贺重明的例句池
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("贺重明号伯安，人称重明先生。",),
            ("重明说道：「今日天气不错。」",),
        ]

        with patch("src.metrics.text_utils.split_sentences") as mock_split:
            mock_split.side_effect = lambda text: [text]

            result = _build_sentence_pool(mock_conn, ["贺重明"], ["号", "人称"], "run-test")

            self.assertIn("贺重明", result)
            self.assertIn("贺重明号伯安", result["贺重明"])

    def test_no_variant_matching_when_short_is_independent(self) -> None:
        """
        短形式是独立候选时，不应将句子归入长形式的例句池
        例如：重明是独立候选，包含"重明"的句子不应归入贺重明
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("重明说道：「今日天气不错。」",),
        ]

        with patch("src.metrics.text_utils.split_sentences") as mock_split:
            mock_split.side_effect = lambda text: [text]

            result = _build_sentence_pool(mock_conn, ["贺重明", "重明"], [], "run-test")

            self.assertIn("重明", result)
            self.assertIn("重明说道", result["重明"])
            self.assertNotIn("贺重明", result)

    def test_full_name_always_matches(self) -> None:
        """
        完整名字始终能匹配
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("贺重明走进了房间。",),
        ]

        with patch("src.metrics.text_utils.split_sentences") as mock_split:
            mock_split.side_effect = lambda text: [text]

            result = _build_sentence_pool(mock_conn, ["贺重明"], [], "run-test")

            self.assertIn("贺重明", result)
            self.assertIn("贺重明走进了房间", result["贺重明"])

    def test_multiple_names_with_variants(self) -> None:
        """
        多个候选名，各自有变体，正确匹配
        """
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("重明和伯安一起来了。",),
            ("李四说道：「你好。」",),
        ]

        with patch("src.metrics.text_utils.split_sentences") as mock_split:
            mock_split.side_effect = lambda text: [text]

            result = _build_sentence_pool(mock_conn, ["贺重明", "李四"], [], "run-test")

            self.assertIn("贺重明", result)
            self.assertIn("重明和伯安", result["贺重明"])
            self.assertIn("李四", result)


if __name__ == "__main__":
    unittest.main()
