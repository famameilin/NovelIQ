"""
创建时间: 2026-03-24
任务: decouple-unified-client-phase5
修改内容: 迁移 parse_active_entities 专项用例并独立成文件
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser import parse_active_entities


class TestParseActiveEntities(unittest.TestCase):
    """测试 parse_active_entities 函数。"""

    def setUp(self):
        self.parse_func = parse_active_entities

    def test_parse_multiline_format(self):
        active_entities = """【近期活跃角色】
- 贺伯安（主角）：修炼；平静（0）
- 林清婉（女主）：等待；期待（1）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["贺伯安", "林清婉"])

    def test_parse_plain_line_format(self):
        active_entities = """【近期活跃角色】
赵兰英（母亲）：焦虑（1）
贺铮：受伤；愤怒（2）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["赵兰英", "贺铮"])

    def test_parse_multiline_with_chinese_colon(self):
        active_entities = """【近期活跃角色】
- 张三（主角）：行走；平静（0）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["张三"])

    def test_parse_multiline_with_english_colon(self):
        active_entities = """【近期活跃角色】
- 李四: 行走; 平静(0)"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["李四"])

    def test_parse_empty_string(self):
        result = self.parse_func("")
        self.assertEqual(result, [])

    def test_parse_none(self):
        result = self.parse_func(None)
        self.assertEqual(result, [])

    def test_parse_comma_separated_format(self):
        active_entities = "张三, 李四, 王五"
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["张三", "李四", "王五"])

    def test_parse_comma_separated_with_colon(self):
        active_entities = "张三:主角, 李四:配角"
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["张三", "李四"])

    def test_parse_multiline_with_header_only(self):
        active_entities = "【近期活跃角色】\n"
        result = self.parse_func(active_entities)
        self.assertEqual(result, [])

    def test_parse_multiline_complex_names(self):
        active_entities = """【近期活跃角色】
- 欧阳锋（反派）：练功；愤怒（2）
- 独孤求败（隐士）：等待；平静（0）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["欧阳锋", "独孤求败"])

    def test_parse_multiline_single_entity(self):
        active_entities = """【近期活跃角色】
- 贺伯安（主角）：修炼；平静（0）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["贺伯安"])

    def test_parse_whitespace_handling(self):
        active_entities = """【近期活跃角色】
-   张三  （主角）  ：行走；平静（0）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["张三"])

    def test_parse_real_format_from_entity_registry(self):
        active_entities = """【近期活跃角色】
- 贺伯安（protagonist）：修炼；平静（0）
- 林清婉（love_interest）：等待；期待（1）
- 王老汉（other）：旁观；好奇（0）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["贺伯安", "林清婉", "王老汉"])


if __name__ == "__main__":
    unittest.main()
