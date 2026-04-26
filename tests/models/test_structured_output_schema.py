"""
创建时间: 2026-04-20
创建者: Codex
任务: fix-phase2-response-format-schema
说明: 回归测试 strict structured output 的 JSON Schema 构建，避免云端接口因 additionalProperties 缺失而拒绝请求。
"""

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.disambiguation.api_call import call_disambiguate_api
from src.models.local.disambiguation.result_builder import normalize_disambiguate_response
from src.models.local.schema import (
    AliasConfidenceRecord,
    CanonicalDecisionRecord,
    CloudDisambiguateResponseModel,
    DialogueAttributionResult,
    DisambiguateResponseModel,
    EntityTypeRecord,
    EvidenceSourceRecord,
    ForeshadowingResult,
)


def _extract_optional_literal_enum(property_schema: dict[str, Any]) -> list[str]:
    """提取 Optional[Literal[...]] 字段中的枚举值。"""
    for candidate in property_schema.get("anyOf", []):
        if "enum" in candidate:
            return list(candidate["enum"])
    return list(property_schema.get("enum", []))


class TestStructuredOutputSchema(unittest.TestCase):
    def setUp(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-phase2-response-format-schema
        说明: 构造本地 client，仅验证 schema builder，不触发真实模型调用。
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        self.annotation_client = AnnotationClient(
            task_type="annotation",
            config=config,
            client=MagicMock(),
        )
        self.disambiguation_client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=MagicMock(),
        )

    def test_foreshadowing_schema_forbids_unknown_root_fields(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-phase2-response-format-schema
        说明: 锁定 phase2 伏笔结果根对象会显式输出 additionalProperties=false，
        且 required 会覆盖所有 properties。
        """
        schema = self.annotation_client._build_json_schema(ForeshadowingResult)["json_schema"]["schema"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], list(schema["properties"].keys()))

    def test_foreshadowing_schema_uses_current_chinese_type_enum(self) -> None:
        """
        创建时间: 2026-04-26
        任务: phase2-strong-foreshadowing
        说明: 锁定 Phase2 当前公开合同已经切换到中文伏笔类型枚举，不再回退到 causal/thematic。
        """
        schema = self.annotation_client._build_json_schema(ForeshadowingResult)["json_schema"]["schema"]
        is_strong_setup = schema["properties"]["is_strong_setup"]
        foreshadowing_type = schema["properties"]["foreshadowing_type"]
        setup_kind = schema["properties"]["setup_kind"]
        confidence = schema["properties"]["confidence"]
        why_unresolved_now = schema["properties"]["why_unresolved_now"]
        expected_payoff_family = schema["properties"]["expected_payoff_family"]

        self.assertEqual(
            _extract_optional_literal_enum(foreshadowing_type),
            ["物件", "对话", "场景", "人物行为", "其他"],
        )
        self.assertEqual(is_strong_setup["type"], "boolean")
        self.assertEqual(
            _extract_optional_literal_enum(setup_kind),
            ["异常物件", "异常规则", "隐藏身份", "明确承诺", "明确威胁", "倒计时", "未解释能力", "因果引线", "其他"],
        )
        self.assertEqual(confidence["enum"], ["high", "medium", "low"])
        self.assertEqual(why_unresolved_now["type"], "string")
        self.assertEqual(expected_payoff_family["type"], "string")

    def test_nested_model_schema_forbids_unknown_fields(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-phase2-response-format-schema
        说明: 锁定嵌套 $defs 模型也会被一并收紧，避免 phase3/phase4 后续再报同类错误。
        """
        schema = self.annotation_client._build_json_schema(DialogueAttributionResult)["json_schema"]["schema"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], list(schema["properties"].keys()))
        self.assertIs(schema["$defs"]["DialogueRecordSchema"]["additionalProperties"], False)
        self.assertEqual(
            schema["$defs"]["DialogueRecordSchema"]["required"],
            list(schema["$defs"]["DialogueRecordSchema"]["properties"].keys()),
        )

    def test_mapping_schema_keeps_value_definition(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-phase2-response-format-schema
        说明: dict[str, T] 映射字段仍需保留 value schema，不能被误改成不允许任何动态键。
        """
        schema = self.disambiguation_client._build_json_schema(DisambiguateResponseModel)["json_schema"]["schema"]
        canonical_decisions = schema["properties"]["canonical_decisions"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], list(schema["properties"].keys()))
        self.assertIsInstance(canonical_decisions["additionalProperties"], dict)
        self.assertEqual(canonical_decisions["additionalProperties"]["type"], "string")

    def test_internal_thinking_field_is_excluded_from_response_schema(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-disambig-cloud-schema-internal-field
        说明: `_thinking_content` / `_reasoning_tokens` 属于运行时内部回填字段，不应要求模型通过 JSON 返回，
        否则云端 strict schema 校验可能把内部字段也当成公开契约。
        """
        schema = self.disambiguation_client._build_json_schema(DisambiguateResponseModel)["json_schema"]["schema"]
        self.assertNotIn("_thinking_content", schema["properties"])
        self.assertNotIn("_thinking_content", schema["required"])
        self.assertNotIn("_reasoning_tokens", schema["properties"])
        self.assertNotIn("_reasoning_tokens", schema["required"])
        self.assertEqual(schema["required"], list(schema["properties"].keys()))

    def test_cloud_disambiguation_schema_uses_record_arrays_for_dynamic_mappings(self) -> None:
        """
        创建时间: 2026-04-20
        创建者: Codex
        任务: fix-cloud-disambig-mapping-schema
        说明: 云端 provider 不兼容 dict[str, T] 形式的 strict schema，
        因此 cloud 版消歧响应必须改成显式数组记录，避免再次触发 invalid_json_schema。
        """
        schema = self.disambiguation_client._build_json_schema(CloudDisambiguateResponseModel)["json_schema"]["schema"]
        canonical_decisions = schema["properties"]["canonical_decisions"]
        alias_confidence = schema["properties"]["alias_confidence"]
        entity_types = schema["properties"]["entity_types"]
        evidence_sources = schema["properties"]["evidence_sources"]

        self.assertEqual(canonical_decisions["type"], "array")
        self.assertEqual(alias_confidence["type"], "array")
        self.assertEqual(entity_types["type"], "array")
        self.assertEqual(evidence_sources["type"], "array")
        self.assertNotIn("additionalProperties", canonical_decisions)

    def test_cloud_disambiguation_normalization_preserves_runtime_reasoning_fields(self) -> None:
        """
        创建时间: 2026-04-21
        创建者: Codex
        任务: fix-disambig-result-builder-thinking-and-types
        说明: 云端兼容响应在归一化回内部标准模型时，不能把 API 层单独回填的
        thinking_content / reasoning_tokens 丢掉。
        """
        cloud_response = CloudDisambiguateResponseModel(
            canonical_decisions=[CanonicalDecisionRecord(name="灰衣人", canonical="白芷")],
            alias_confidence=[AliasConfidenceRecord(name="灰衣人", confidence="high")],
            entity_types=[EntityTypeRecord(name="白芷", entity_type="character")],
            evidence_sources=[EvidenceSourceRecord(name="灰衣人", sources=["原文例句"])],
        ).model_copy(update={"thinking_content": "她其实就是白芷", "reasoning_tokens": 42})

        normalized = normalize_disambiguate_response(cloud_response)

        self.assertEqual(normalized.canonical_decisions["灰衣人"], "白芷")
        self.assertEqual(normalized.alias_confidence["灰衣人"], "high")
        self.assertEqual(normalized.thinking_content, "她其实就是白芷")
        self.assertEqual(normalized.reasoning_tokens, 42)

    def test_cloud_disambiguation_rejects_legacy_mapping_shape(self) -> None:
        """
        创建时间: 2026-04-24
        任务: unify-disambig-transport-record-arrays
        说明: 消歧传输层已经统一为记录数组；旧 dict 映射应直接校验失败，避免静默吞掉格式回退。
        """
        with self.assertRaises(ValidationError):
            CloudDisambiguateResponseModel.model_validate(
                {
                    "canonical_decisions": {
                        "叶哲泰": "叶哲泰",
                        "一名男红卫兵": "男红卫兵",
                    },
                    "alias_confidence": {
                        "叶哲泰": "high",
                        "一名男红卫兵": "medium",
                    },
                    "entity_types": {
                        "叶哲泰": "character",
                        "男红卫兵": "group",
                    },
                    "entity_relations": [
                        {"from": "男红卫兵", "to": "叶哲泰", "type": "敌对"},
                    ],
                    "evidence_sources": {
                        "一名男红卫兵": ["原文例句"],
                    },
                }
            )

    def test_disambiguation_api_always_uses_record_array_transport_model(self) -> None:
        """
        创建时间: 2026-04-24
        任务: unify-disambig-transport-record-arrays
        说明: 本地与云端消歧调用都先使用记录数组传输模型，返回后再归一化为内部 dict 模型。
        """
        config = TaskModelConfig(
            base_url="http://127.0.0.1:8000/v1",
            model="test-model",
            api_key="test-key",
        )
        client = DisambiguationClient(
            task_type="incremental_disambig",
            config=config,
            client=MagicMock(),
        )
        parsed = CloudDisambiguateResponseModel(
            canonical_decisions=[CanonicalDecisionRecord(name="灰衣人", canonical="白芷")],
            alias_confidence=[AliasConfidenceRecord(name="灰衣人", confidence="high")],
            entity_types=[EntityTypeRecord(name="白芷", entity_type="character")],
        )

        async def fake_call_structured_output(_client: object, request: Any) -> object:
            self.assertIs(request.response_model, CloudDisambiguateResponseModel)
            return SimpleNamespace(
                parsed=parsed,
                raw_response=None,
                response_text="{}",
                thinking_content=None,
                reasoning_tokens=None,
            )

        with patch(
            "src.models.local.disambiguation.api_call.call_structured_output",
            new=fake_call_structured_output,
        ):
            normalized = asyncio.run(
                call_disambiguate_api(
                    client=client,
                    config=config,
                    messages=[{"role": "user", "content": "请输出 JSON"}],
                    log_type="disambiguate_characters",
                )
            )

        self.assertEqual(normalized.canonical_decisions["灰衣人"], "白芷")
        self.assertEqual(normalized.alias_confidence["灰衣人"], "high")


if __name__ == "__main__":
    unittest.main()
