"""
标注配置单元测试

创建时间: 2026-03-18
任务: entity-type-relation-extraction
说明: 测试标注静态常量与 runtime 配置解析

修改时间: 2026-04-20
任务: runtime-behavior-settings
修改内容: 删除对 ANNOTATION_CONFIG 的依赖，改为验证 constants 与 runtime schema
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config.constants import (
    VALID_ACTION_TYPES,
    VALID_CLUE_TYPES,
    VALID_ENTITY_TYPES,
    VALID_RELATION_TYPES,
    VALID_ROLE_FUNCTIONS,
)
from src.config.schemas import _parse_runtime_settings
from src.config.schemas.analysis import _parse_analysis_settings


class TestAnnotationConstants(unittest.TestCase):
    """
    创建时间: 2026-03-18
    任务: entity-type-relation-extraction
    说明: 测试 annotation 静态业务常量
    """

    def test_valid_relation_types(self) -> None:
        """测试关系类型常量"""
        expected = {"师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从", "友情"}
        self.assertEqual(set(VALID_RELATION_TYPES), expected)

    def test_valid_entity_types(self) -> None:
        """测试实体类型常量"""
        expected = ("character", "group", "organization", "creature", "artifact")
        self.assertEqual(tuple(VALID_ENTITY_TYPES), expected)

    def test_valid_role_functions(self) -> None:
        """测试角色功能常量"""
        expected = ("主体", "客体", "发送者", "接收者", "帮助者", "反对者")
        self.assertEqual(tuple(VALID_ROLE_FUNCTIONS), expected)

    def test_valid_action_types(self) -> None:
        """测试行为类型常量"""
        expected = ("战斗", "逃跑", "对话", "决策", "移动", "情感", "其他")
        self.assertEqual(tuple(VALID_ACTION_TYPES), expected)

    def test_valid_clue_types(self) -> None:
        """测试线索类型常量"""
        expected = (
            "none",
            "self_introduction",
            "named_by_other",
            "alias_revealed",
            "appearance_desc",
            "unique_body_marker",
            "kinship_identity",
            "naming_scene",
        )
        self.assertEqual(tuple(VALID_CLUE_TYPES), expected)


class TestRuntimeSettings(unittest.TestCase):
    """测试 runtime 配置解析。"""

    def test_parse_runtime_settings_defaults(self) -> None:
        """测试当前 runtime 默认值"""
        runtime = _parse_runtime_settings(None)
        self.assertFalse(hasattr(runtime, "annotation"))
        self.assertEqual(runtime.disambiguation.max_retries, 3)
        self.assertEqual(runtime.diagnosis.max_retries, 3)

    def test_parse_runtime_settings_rejects_retired_annotation_namespace(self) -> None:
        """
        2026-08-03 用于拒绝已退役的 runtime.annotation 阶段配置命名空间
        """
        with self.assertRaisesRegex(ValueError, "runtime.annotation"):
            _parse_runtime_settings({"annotation": {"phase3_max_retries": 3}})

    def test_parse_runtime_settings_rejects_non_positive_values(self) -> None:
        """
        2026-08-03 用于保持当前诊断 runtime 数值配置的正整数校验
        """
        with self.assertRaises(ValueError):
            _parse_runtime_settings({"diagnosis": {"max_retries": 0}})

    def test_parse_analysis_settings_defaults_include_hierarchical_relation_types(self) -> None:
        analysis = _parse_analysis_settings(None)
        self.assertEqual(
            analysis.valid_hierarchical_relation_types,
            [
                "belongs_to",
                "member_of",
                "leader_of",
                "affiliated_with",
                "father_of",
                "son_of",
                "parent_of",
                "child_of",
                "sibling_of",
                "spouse_of",
            ],
        )


if __name__ == "__main__":
    unittest.main()
