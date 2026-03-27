"""
标注配置单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试标注配置常量
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config.schemas import ANNOTATION_CONFIG


class TestAnnotationConfig(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 ANNOTATION_CONFIG 配置常量
    """

    def test_valid_interpersonal_relation_types(self) -> None:
        """测试人际关系类型常量"""
        expected = ["师徒", "敌对", "盟友", "爱慕", "家族", "利益", "主从"]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_interpersonal_relation_types,
            expected
        )

    def test_valid_hierarchical_relation_types(self) -> None:
        """测试层级关系类型常量"""
        expected = [
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
        ]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_hierarchical_relation_types,
            expected
        )

    def test_valid_entity_types(self) -> None:
        """测试实体类型常量"""
        expected = ["character", "group", "organization"]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_entity_types,
            expected
        )

    def test_valid_role_functions(self) -> None:
        """测试角色功能常量"""
        expected = ["主体", "客体", "发送者", "接收者", "帮助者", "反对者"]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_role_functions,
            expected
        )

    def test_valid_action_types(self) -> None:
        """测试行为类型常量"""
        expected = ["战斗", "逃跑", "对话", "决策", "移动", "情感", "其他"]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_action_types,
            expected
        )

    def test_valid_clue_types(self) -> None:
        """测试线索类型常量"""
        expected = [
            "none",
            "self_introduction",
            "named_by_other",
            "alias_revealed",
            "appearance_desc",
            "unique_body_marker",
            "kinship_identity",
            "naming_scene",
        ]
        self.assertEqual(
            ANNOTATION_CONFIG.valid_clue_types,
            expected
        )

    def test_retry_config(self) -> None:
        """测试重试配置"""
        self.assertEqual(ANNOTATION_CONFIG.phase_max_retries, 3)
        self.assertEqual(ANNOTATION_CONFIG.disambig_max_retries, 3)
        self.assertEqual(ANNOTATION_CONFIG.validation_max_retries, 3)

    def test_checkpoint_interval(self) -> None:
        """测试检查点间隔"""
        self.assertEqual(ANNOTATION_CONFIG.checkpoint_interval, 50)


if __name__ == "__main__":
    unittest.main()
