"""
创建时间: 2026-04-20
创建者: Codex
任务: fix-phase2-response-format-schema
说明: 回归测试 strict structured output 的 JSON Schema 构建，避免云端接口因 additionalProperties 缺失而拒绝请求。
"""

import unittest
from unittest.mock import MagicMock

from src.config import TaskModelConfig
from src.models.annotation import AnnotationClient
from src.models.disambiguation import DisambiguationClient
from src.models.local.schema import DialogueAttributionResult, DisambiguateResponseModel, ForeshadowingResult


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
        说明: `_thinking_content` 属于运行时内部回填字段，不应要求模型通过 JSON 返回，
        否则云端 strict schema 校验可能把内部字段也当成公开契约。
        """
        schema = self.disambiguation_client._build_json_schema(DisambiguateResponseModel)["json_schema"]["schema"]
        self.assertNotIn("_thinking_content", schema["properties"])
        self.assertNotIn("_thinking_content", schema["required"])
        self.assertEqual(schema["required"], list(schema["properties"].keys()))


if __name__ == "__main__":
    unittest.main()
