"""
消歧循环依赖检测单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试循环依赖检测算法
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.workflows.annotate_helpers.disambiguation import (
    _extract_retryable_relations,
    detect_cycle_in_relations,
)


class TestDetectCycleInRelations(unittest.TestCase):
    """
    创建时间: 2026-03-18
    创建者: TraeAI
    任务: entity-type-relation-extraction
    说明: 测试 detect_cycle_in_relations 函数
    """

    def test_no_cycle_simple(self) -> None:
        """测试无循环的简单关系"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_simple_cycle(self) -> None:
        """测试简单循环 A->B->A"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "A", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 2)
        self.assertEqual(len(paths), 1)
        # 检查循环路径包含 A 和 B
        self.assertIn("A", paths[0])
        self.assertIn("B", paths[0])

    def test_three_node_cycle(self) -> None:
        """测试三节点循环 A->B->C->A"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
            {"from": "C", "to": "A", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 3)
        self.assertEqual(len(paths), 1)
        # 检查循环路径包含 A, B, C
        self.assertIn("A", paths[0])
        self.assertIn("B", paths[0])
        self.assertIn("C", paths[0])

    def test_cycle_with_branch(self) -> None:
        """测试带分支的循环"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
            {"from": "C", "to": "A", "type": "belongs_to"},  # 循环
            {"from": "A", "to": "D", "type": "belongs_to"},  # 分支
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        # 所有涉及循环节点的关系都应该被跳过
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 4)
        self.assertEqual(len(paths), 1)

    def test_multiple_cycles(self) -> None:
        """测试多个独立循环"""
        relations = [
            # 第一个循环 A->B->A
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "A", "type": "belongs_to"},
            # 第二个循环 C->D->C
            {"from": "C", "to": "D", "type": "belongs_to"},
            {"from": "D", "to": "C", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 4)
        self.assertEqual(len(paths), 2)

    def test_empty_relations(self) -> None:
        """测试空关系列表"""
        relations: list[dict[str, str]] = []
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_self_reference(self) -> None:
        """测试自引用 A->A"""
        relations = [
            {"from": "A", "to": "A", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 1)
        self.assertEqual(len(paths), 1)

    def test_complex_graph_with_partial_cycle(self) -> None:
        """测试复杂图，部分有循环，部分无循环"""
        relations = [
            # 无循环部分
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
            # 循环部分
            {"from": "D", "to": "E", "type": "belongs_to"},
            {"from": "E", "to": "F", "type": "belongs_to"},
            {"from": "F", "to": "D", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        # 无循环部分应该保留
        self.assertEqual(len(valid), 2)
        # 循环部分应该被跳过
        self.assertEqual(len(skipped), 3)
        self.assertEqual(len(paths), 1)


class TestExtractRetryableRelations(unittest.TestCase):
    def test_keeps_retryable_skip_reasons(self) -> None:
        skipped = [
            {"relation": {"from": "A", "to": "B", "type": "member_of"}, "reason": "from_entity_not_found"},
            {"relation": {"from": "B", "to": "C", "type": "belongs_to"}, "reason": "to_entity_not_found"},
            {"relation": {"from": "C", "to": "D", "type": "affiliated_with"}, "reason": "insert_error: timeout"},
        ]

        retryable = _extract_retryable_relations(skipped)
        self.assertEqual(len(retryable), 3)

    def test_ignores_non_retryable_or_malformed_entries(self) -> None:
        skipped = [
            {"relation": {"from": "A", "to": "B", "type": "member_of"}, "reason": "invalid_relation_type"},
            {"relation": {"from": "A", "to": "B", "type": "member_of"}, "reason": "missing_fields"},
            {"from": "X", "to": "Y", "type": "member_of"},  # cycle_skipped raw relation format
            {"relation": "not_a_dict", "reason": "insert_error: x"},
        ]

        retryable = _extract_retryable_relations(skipped)
        self.assertEqual(retryable, [])


if __name__ == "__main__":
    unittest.main()
