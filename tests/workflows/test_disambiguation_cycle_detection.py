"""
消歧循环依赖检测单元测试

创建时间: 2026-03-18
创建者: TraeAI
任务: entity-type-relation-extraction
说明: 测试循环依赖检测算法

修改时间: 2026-03-31
修改者: TraeAI
任务: fix-cycle-detection-bug
修改内容: 新增18个测试用例覆盖跨类型亲子关系配对
"""

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.workflows.annotate_helpers.disambiguation import (
    _extract_retryable_relations,
    _is_valid_inverse_pair,
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
        self.assertIn("A", paths[0])
        self.assertIn("B", paths[0])
        self.assertIn("C", paths[0])

    def test_cycle_with_branch(self) -> None:
        """测试带分支的循环"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
            {"from": "C", "to": "A", "type": "belongs_to"},
            {"from": "A", "to": "D", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 0)
        self.assertEqual(len(skipped), 4)
        self.assertEqual(len(paths), 1)

    def test_multiple_cycles(self) -> None:
        """测试多个独立循环"""
        relations = [
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "A", "type": "belongs_to"},
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
            {"from": "A", "to": "B", "type": "belongs_to"},
            {"from": "B", "to": "C", "type": "belongs_to"},
            {"from": "D", "to": "E", "type": "belongs_to"},
            {"from": "E", "to": "F", "type": "belongs_to"},
            {"from": "F", "to": "D", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 3)
        self.assertEqual(len(paths), 1)

    def test_sibling_of_self_inverse(self) -> None:
        """测试 sibling_of 自逆对不构成循环"""
        relations = [
            {"from": "A", "to": "B", "type": "sibling_of"},
            {"from": "B", "to": "A", "type": "sibling_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_spouse_of_self_inverse(self) -> None:
        """测试 spouse_of 自逆对不构成循环"""
        relations = [
            {"from": "A", "to": "B", "type": "spouse_of"},
            {"from": "B", "to": "A", "type": "spouse_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_child_of_parent_of_cross_type(self) -> None:
        """测试 child_of + parent_of 跨类型配对不构成循环"""
        relations = [
            {"from": "赵兰英", "to": "伯安", "type": "parent_of"},
            {"from": "伯安", "to": "赵兰英", "type": "child_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_child_of_father_of_cross_type(self) -> None:
        """测试 child_of + father_of 跨类型配对不构成循环"""
        relations = [
            {"from": "伯安", "to": "贺铮", "type": "child_of"},
            {"from": "贺铮", "to": "伯安", "type": "father_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_parent_of_child_of_cross_type(self) -> None:
        """测试 parent_of + child_of 跨类型配对不构成循环"""
        relations = [
            {"from": "赵兰英", "to": "伯安", "type": "parent_of"},
            {"from": "伯安", "to": "赵兰英", "type": "child_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_parent_of_son_of_cross_type(self) -> None:
        """测试 parent_of + son_of 跨类型配对不构成循环"""
        relations = [
            {"from": "贺铮", "to": "伯安", "type": "parent_of"},
            {"from": "伯安", "to": "贺铮", "type": "son_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_father_of_child_of_cross_type(self) -> None:
        """测试 father_of + child_of 跨类型配对不构成循环"""
        relations = [
            {"from": "贺铮", "to": "伯安", "type": "father_of"},
            {"from": "伯安", "to": "贺铮", "type": "child_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_father_of_son_of_cross_type(self) -> None:
        """测试 father_of + son_of 跨类型配对不构成循环"""
        relations = [
            {"from": "贺铮", "to": "伯安", "type": "father_of"},
            {"from": "伯安", "to": "贺铮", "type": "son_of"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 2)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)

    def test_mixed_parent_child_with_belongs_to(self) -> None:
        """测试混合关系：亲子跨类型对 + belongs_to"""
        relations = [
            {"from": "赵兰英", "to": "伯安", "type": "parent_of"},
            {"from": "贺铮", "to": "伯安", "type": "father_of"},
            {"from": "伯安", "to": "赵兰英", "type": "child_of"},
            {"from": "伯安", "to": "贺铮", "type": "child_of"},
            {"from": "周凤兰", "to": "贺府", "type": "belongs_to"},
            {"from": "赵兰英", "to": "贺府", "type": "belongs_to"},
            {"from": "伯安", "to": "贺府", "type": "belongs_to"},
        ]
        valid, skipped, paths = detect_cycle_in_relations(relations)

        self.assertEqual(len(valid), 7)
        self.assertEqual(len(skipped), 0)
        self.assertEqual(len(paths), 0)


class TestIsValidInversePair(unittest.TestCase):
    """
    创建时间: 2026-03-31
    创建者: TraeAI
    任务: fix-cycle-detection-bug
    说明: 直接测试 _is_valid_inverse_pair 函数
    """

    def test_child_of_parent_of_valid(self) -> None:
        """测试 child_of + parent_of 是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "child_of"},
            {"from": "B", "to": "A", "type": "parent_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_child_of_father_of_valid(self) -> None:
        """测试 child_of + father_of 是合法逆对（跨类型）"""
        relations = [
            {"from": "A", "to": "B", "type": "child_of"},
            {"from": "B", "to": "A", "type": "father_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_father_of_son_of_valid(self) -> None:
        """测试 father_of + son_of 是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "father_of"},
            {"from": "B", "to": "A", "type": "son_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_parent_of_son_of_valid(self) -> None:
        """测试 parent_of + son_of 是合法逆对（跨类型）"""
        relations = [
            {"from": "A", "to": "B", "type": "parent_of"},
            {"from": "B", "to": "A", "type": "son_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_sibling_of_bidirectional_valid(self) -> None:
        """测试 sibling_of 双向是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "sibling_of"},
            {"from": "B", "to": "A", "type": "sibling_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_spouse_of_bidirectional_valid(self) -> None:
        """测试 spouse_of 双向是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "spouse_of"},
            {"from": "B", "to": "A", "type": "spouse_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertTrue(result)

    def test_invalid_mismatch_types(self) -> None:
        """测试 child_of + sibling_of 不是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "child_of"},
            {"from": "B", "to": "A", "type": "sibling_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertFalse(result)

    def test_single_direction_not_valid(self) -> None:
        """测试只有单向关系不是合法逆对"""
        relations = [
            {"from": "A", "to": "B", "type": "child_of"},
        ]
        result = _is_valid_inverse_pair(relations, "A", "B")
        self.assertFalse(result)


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
            {"from": "X", "to": "Y", "type": "member_of"},
            {"relation": "not_a_dict", "reason": "insert_error: x"},
        ]

        retryable = _extract_retryable_relations(skipped)
        self.assertEqual(retryable, [])


if __name__ == "__main__":
    unittest.main()
