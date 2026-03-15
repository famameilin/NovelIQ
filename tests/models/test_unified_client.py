"""
创建时间: 2026-03-13
创建者: TraeAI
任务: refactor-model-interaction-layer
修改内容: 更新测试以测试迁移后的 parse_active_entities 函数
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.parser import parse_active_entities
from src.models.local.unified_client import UnifiedModelClient


class MockUnifiedModelClient(UnifiedModelClient):
    """
    修改时间: 2026-03-13
    修改者: TraeAI
    修改内容: 修复 Mock 类初始化问题，避免触发父类的 property setter
    """
    def __init__(self):
        self.__dict__['_novel_id_value'] = None
        self.__dict__['_token_usage_callback_value'] = None
        self._task_type = "annotation"
        self._analysis_logger = None
        self._annotation_client = MagicMock()
        self._annotation_client._parse_active_entities = parse_active_entities
        self._disambiguation_client = MagicMock()
        self._config = MagicMock()


class TestParseActiveEntities(unittest.TestCase):
    """
    测试 parse_active_entities 函数
    
    修改时间: 2026-03-13
    修改者: TraeAI
    修改内容: 直接测试 parser.parse_active_entities 函数
    """
    def setUp(self):
        self.parse_func = parse_active_entities

    def test_parse_multiline_format(self):
        active_entities = """【近期活跃角色】
- 贺伯安（主角）：修炼；平静（0）
- 林清婉（女主）：等待；期待（1）"""
        result = self.parse_func(active_entities)
        self.assertEqual(result, ["贺伯安", "林清婉"])

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


class TestUnifiedClientProxy(unittest.TestCase):
    """
    测试 UnifiedModelClient 对 parse_active_entities 的代理调用
    
    修改时间: 2026-03-13
    创建者: TraeAI
    任务: refactor-model-interaction-layer
    """
    def setUp(self):
        self.client = MockUnifiedModelClient()

    def test_proxy_parse_active_entities(self):
        active_entities = """【近期活跃角色】
- 贺伯安（主角）：修炼；平静（0）"""
        result = self.client._parse_active_entities(active_entities)
        self.assertEqual(result, ["贺伯安"])


if __name__ == "__main__":
    unittest.main()
