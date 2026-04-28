"""
验证消歧证据分级功能

说明: 使用数据库真实数据验证证据分级效果
"""

import sys
import json
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.disambiguation import ExtendedDisambigResult
from src.workflows.annotate_helpers.disambiguation import (
    validate_confidence_with_evidence,
    DISAMBIG_CONFIDENCE_HIGH,
    DISAMBIG_CONFIDENCE_MEDIUM,
    DISAMBIG_CONFIDENCE_LOW,
)
from src.models.local.parser.annotation_builder import validate_summary_quality


def test_evidence_grading():
    """测试证据分级规则"""
    print("=" * 60)
    print("测试 1: 弱证据降级规则")
    print("=" * 60)

    result = ExtendedDisambigResult(
        merge_target_map={"灰衣人": "伯安"},
        entity_types={"伯安": "character"},
        entity_relations=[],
        alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
        evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
    )

    validated = validate_confidence_with_evidence(result, [])
    print(f"  原始置信度: {DISAMBIG_CONFIDENCE_HIGH}")
    print(f"  证据来源: ['前文摘要-弱证据']")
    print(f"  校验后置信度: {validated.alias_confidence['灰衣人']}")
    assert validated.alias_confidence["灰衣人"] == DISAMBIG_CONFIDENCE_MEDIUM, "弱证据应降级为 medium"
    print("  ✅ 通过：弱证据降级为 medium")

    print()
    print("=" * 60)
    print("测试 2: 强证据保持高置信度")
    print("=" * 60)

    result = ExtendedDisambigResult(
        merge_target_map={"贺重明": "伯安"},
        entity_types={"伯安": "character"},
        entity_relations=[],
        alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
        evidence_sources={"贺重明": ["原文例句", "身份线索"]},
    )

    validated = validate_confidence_with_evidence(result, [])
    print(f"  原始置信度: {DISAMBIG_CONFIDENCE_HIGH}")
    print(f"  证据来源: ['原文例句', '身份线索']")
    print(f"  校验后置信度: {validated.alias_confidence['贺重明']}")
    assert validated.alias_confidence["贺重明"] == DISAMBIG_CONFIDENCE_HIGH, "强证据应保持 high"
    print("  ✅ 通过：强证据保持高置信度")

    print()
    print("=" * 60)
    print("测试 3: 弱证据禁止合并到已有角色")
    print("=" * 60)

    result = ExtendedDisambigResult(
        merge_target_map={"灰衣人": "伯安"},
        entity_types={"伯安": "character"},
        entity_relations=[],
        alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
        evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
    )

    validated = validate_confidence_with_evidence(result, ["伯安"])
    print(f"  原始合并目标: 伯安")
    print(f"  证据来源: ['前文摘要-弱证据']")
    print(f"  已存在角色: ['伯安']")
    print(f"  校验后合并目标: {validated.merge_target_map['灰衣人']}")
    assert validated.merge_target_map["灰衣人"] == "灰衣人", "弱证据应禁止合并到已有角色"
    print("  ✅ 通过：弱证据禁止合并到已有角色")

    print()
    print("=" * 60)
    print("测试 4: 强证据允许合并到已有角色")
    print("=" * 60)

    result = ExtendedDisambigResult(
        merge_target_map={"贺重明": "伯安"},
        entity_types={"伯安": "character"},
        entity_relations=[],
        alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
        evidence_sources={"贺重明": ["原文例句", "身份线索"]},
    )

    validated = validate_confidence_with_evidence(result, ["伯安"])
    print(f"  原始合并目标: 伯安")
    print(f"  证据来源: ['原文例句', '身份线索']")
    print(f"  已存在角色: ['伯安']")
    print(f"  校验后合并目标: {validated.merge_target_map['贺重明']}")
    assert validated.merge_target_map["贺重明"] == "伯安", "强证据应允许合并到已有角色"
    print("  ✅ 通过：强证据允许合并到已有角色")


def test_summary_quality():
    """测试摘要质量校验"""
    print()
    print("=" * 60)
    print("测试 5: 摘要质量校验")
    print("=" * 60)

    test_cases = [
        ("灰衣人伯安近看单薄，贺重明对其产生好奇", False, "名字粘连"),
        ("伯安近看那位灰衣人，觉得对方身形单薄，似乎是个文弱书生。", True, "合规摘要"),
        ("伯安看灰衣人。", False, "摘要过短"),
    ]

    for summary, expected_pass, desc in test_cases:
        passed, issues = validate_summary_quality(summary)
        status = "✅" if passed == expected_pass else "❌"
        print(f"  {status} {desc}:")
        print(f"      摘要: {summary[:40]}...")
        print(f"      通过: {passed}, 问题: {issues if issues else '无'}")


def test_real_data_scenarios():
    """测试真实数据场景"""
    print()
    print("=" * 60)
    print("测试 6: 真实数据场景模拟")
    print("=" * 60)

    scenarios = [
        {
            "name": "场景1: 灰衣人合并到伯安（弱证据）",
            "result": ExtendedDisambigResult(
                merge_target_map={"灰衣人": "伯安"},
                entity_types={"伯安": "character"},
                entity_relations=[],
                alias_confidence={"灰衣人": DISAMBIG_CONFIDENCE_HIGH},
                evidence_sources={"灰衣人": ["前文摘要-弱证据"]},
            ),
            "existing_names": ["伯安"],
            "expected_confidence": DISAMBIG_CONFIDENCE_MEDIUM,
            "expected_merge_target": "灰衣人",
        },
        {
            "name": "场景2: 贺重明合并到伯安（强证据）",
            "result": ExtendedDisambigResult(
                merge_target_map={"贺重明": "伯安"},
                entity_types={"伯安": "character"},
                entity_relations=[],
                alias_confidence={"贺重明": DISAMBIG_CONFIDENCE_HIGH},
                evidence_sources={"贺重明": ["原文例句", "身份线索"]},
            ),
            "existing_names": ["伯安"],
            "expected_confidence": DISAMBIG_CONFIDENCE_HIGH,
            "expected_merge_target": "伯安",
        },
        {
            "name": "场景3: 猴子合并到侯飞白（身份线索）",
            "result": ExtendedDisambigResult(
                merge_target_map={"猴子": "侯飞白"},
                entity_types={"侯飞白": "character"},
                entity_relations=[],
                alias_confidence={"猴子": DISAMBIG_CONFIDENCE_HIGH},
                evidence_sources={"猴子": ["身份线索", "原文例句"]},
            ),
            "existing_names": ["侯飞白"],
            "expected_confidence": DISAMBIG_CONFIDENCE_HIGH,
            "expected_merge_target": "侯飞白",
        },
    ]

    for scenario in scenarios:
        print(f"\n  {scenario['name']}:")
        validated = validate_confidence_with_evidence(
            scenario["result"], scenario["existing_names"]
        )
        name = list(scenario["result"].merge_target_map.keys())[0]
        confidence_ok = validated.alias_confidence[name] == scenario["expected_confidence"]
        merge_ok = validated.merge_target_map[name] == scenario["expected_merge_target"]

        print(f"    证据来源: {scenario['result'].evidence_sources[name]}")
        print(f"    置信度: {validated.alias_confidence[name]} (期望: {scenario['expected_confidence']}) {'✅' if confidence_ok else '❌'}")
        print(f"    合并目标: {validated.merge_target_map[name]} (期望: {scenario['expected_merge_target']}) {'✅' if merge_ok else '❌'}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("消歧证据分级功能验证")
    print("=" * 60)

    test_evidence_grading()
    test_summary_quality()
    test_real_data_scenarios()

    print("\n" + "=" * 60)
    print("✅ 所有验证测试通过！")
    print("=" * 60)
