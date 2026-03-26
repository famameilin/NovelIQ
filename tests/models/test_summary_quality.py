import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser.annotation_builder import (
    validate_summary_quality,
    _SUMMARY_MIN_LENGTH,
    _SUMMARY_MAX_LENGTH,
)


class TestSummaryQualityValidation(unittest.TestCase):
    """
    测试摘要质量校验

    创建时间: 2026-03-26
    创建者: TraeAI
    任务: disambiguation-evidence-grading
    说明: 测试摘要长度和名字粘连检测
    """

    def test_valid_summary_passes(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生，但眼神锐利。"
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)

    def test_short_summary_fails(self) -> None:
        summary = "伯安看灰衣人。"
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("过短" in issue for issue in issues))

    def test_long_summary_fails(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生，但眼神中却透露出一股锐利的光芒，让人不敢小觑。" * 2
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("过长" in issue for issue in issues))

    def test_name_adhesion_detected(self) -> None:
        summary = "灰衣人伯安近看觉得对方身形单薄，似乎是个文弱书生。"
        passed, issues = validate_summary_quality(summary)

        self.assertFalse(passed)
        self.assertTrue(any("粘连" in issue for issue in issues))

    def test_empty_summary_passes(self) -> None:
        summary = ""
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)

    def test_min_length_boundary(self) -> None:
        summary = "伯安近看灰衣人，觉得对方身形单薄，似书生。"
        if len(summary) >= _SUMMARY_MIN_LENGTH:
            passed, issues = validate_summary_quality(summary)
            self.assertTrue(passed or not any("过短" in issue for issue in issues))

    def test_max_length_boundary(self) -> None:
        summary = "伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生。"
        if len(summary) <= _SUMMARY_MAX_LENGTH:
            passed, issues = validate_summary_quality(summary)
            self.assertTrue(passed or not any("过长" in issue for issue in issues))

    def test_good_writing_style_passes(self) -> None:
        summary = "灰衣人前来应聘教习，伯安因此留意对方，发现其身形单薄，似书生。"
        passed, issues = validate_summary_quality(summary)

        self.assertTrue(passed)
        self.assertEqual(len(issues), 0)


if __name__ == "__main__":
    unittest.main()
