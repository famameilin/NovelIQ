"""
标注配置单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试标注静态常量与 runtime 配置解析

修改时间: 2026-04-20
修改者: Codex
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


class TestAnnotationConstants(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
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
        """测试 runtime 默认值。"""
        runtime = _parse_runtime_settings(None)
        self.assertEqual(runtime.annotation.phase_max_retries, 3)
        self.assertEqual(runtime.annotation.phase3_max_retries, 3)
        self.assertEqual(runtime.annotation.validation_max_retries, 3)
        self.assertEqual(runtime.annotation.prev_chunks, 3)
        self.assertEqual(runtime.annotation.lookback, 10)
        self.assertEqual(runtime.disambiguation.max_retries, 3)
        self.assertEqual(runtime.diagnosis.max_retries, 3)

    def test_parse_runtime_settings_rejects_non_positive_values(self) -> None:
        """测试 runtime 对非法值执行严格校验。"""
        with self.assertRaises(ValueError):
            _parse_runtime_settings({"annotation": {"phase_max_retries": 0}})


if __name__ == "__main__":
    unittest.main()
