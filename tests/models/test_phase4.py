"""
创建时间: 2026-04-05
创建者: TraeAI
任务: phase4-code-review-fix
说明: 测试 Phase4 关系抽取功能
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config.constants import SYMMETRIC_RELATION_TYPES, VALID_CHANGE_TYPES, VALID_RELATION_TYPES
from src.models.local.annotation.phase4 import (
    Phase4MaxRetriesExceededError,
    _build_phase4_messages,
    _convert_to_snapshots,
    annotate_chunk_phase4,
)
from src.models.local.schema import RelationExtractionResult, RelationRecord


class TestBuildPhase4Messages(unittest.TestCase):
    """
    测试 Phase4 消息构建

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: phase4-code-review-fix
    """

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_success(self, mock_settings: MagicMock) -> None:
        """成功构建消息"""
        mock_settings.prompts.phase4.system = "你是关系抽取专家"
        mock_settings.prompts.phase4.user_template = "文本：{chunk_text}\n人物：{known_characters}"

        messages = _build_phase4_messages("张三打了李四", ["张三", "李四"])

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "你是关系抽取专家")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("张三、李四", messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_with_no_characters(self, mock_settings: MagicMock) -> None:
        """无人物列表时显示'无'"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "{chunk_text}\n{known_characters}"

        messages = _build_phase4_messages("文本内容", None)

        self.assertIn("无", messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_empty_system_prompt_raises(self, mock_settings: MagicMock) -> None:
        """空系统提示抛出 ValueError"""
        mock_settings.prompts.phase4.system = ""
        mock_settings.prompts.phase4.user_template = "template"

        with self.assertRaises(ValueError) as ctx:
            _build_phase4_messages("文本", ["张三"])

        self.assertIn("system prompt is empty", str(ctx.exception))

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_empty_user_template_raises(self, mock_settings: MagicMock) -> None:
        """空用户模板抛出 ValueError"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = ""

        with self.assertRaises(ValueError) as ctx:
            _build_phase4_messages("文本", ["张三"])

        self.assertIn("user template is empty", str(ctx.exception))


class TestConvertToSnapshots(unittest.TestCase):
    """
    测试 LLM 输出转换为 RelationChangeSnapshot

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: phase4-code-review-fix
    """

    def test_convert_single_relation(self) -> None:
        """转换单个关系"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="张三打了李四",
                )
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].from_name, "张三")
        self.assertEqual(snapshots[0].to_name, "李四")
        self.assertEqual(snapshots[0].type, "敌对")
        self.assertEqual(snapshots[0].change, "新建")
        self.assertEqual(snapshots[0].directionality, "directed")
        self.assertEqual(snapshots[0].source_model, "test-model")

    def test_convert_multiple_relations(self) -> None:
        """转换多个关系（盟友是对称类型，会生成反向边）"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据1",
                ),
                RelationRecord(  # type: ignore[arg-type]
                    from_name="王五",
                    to_name="赵六",
                    type="盟友",
                    change="强化",
                    evidence="证据2",
                ),
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 3)

    def test_duplicate_relations_deduplicated(self) -> None:
        """重复关系去重"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据1",
                ),
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据2",
                ),
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 1)

    def test_symmetric_relation_generates_reverse_edge(self) -> None:
        """对称关系自动生成反向边"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="家族",
                    change="无变化",
                    evidence="张三是李四的哥哥",
                )
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 2)
        forward = [s for s in snapshots if s.from_name == "张三"][0]
        reverse = [s for s in snapshots if s.from_name == "李四"][0]

        self.assertEqual(forward.to_name, "李四")
        self.assertEqual(reverse.to_name, "张三")
        self.assertEqual(forward.directionality, "symmetric")
        self.assertEqual(reverse.directionality, "symmetric")

    def test_symmetric_relation_self_loop_not_duplicated(self) -> None:
        """自环对称关系不生成反向边"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="张三",
                    type="家族",
                    change="无变化",
                    evidence="自指",
                )
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 1)

    def test_symmetric_relation_reverse_already_exists(self) -> None:
        """反向边已存在时不重复生成"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="家族",
                    change="无变化",
                    evidence="证据1",
                ),
                RelationRecord(  # type: ignore[arg-type]
                    from_name="李四",
                    to_name="张三",
                    type="家族",
                    change="无变化",
                    evidence="证据2",
                ),
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 2)

    def test_all_symmetric_types_generate_reverse(self) -> None:
        """所有对称类型都生成反向边"""
        for rel_type in SYMMETRIC_RELATION_TYPES:
            result = RelationExtractionResult(
                relations=[
                    RelationRecord(  # type: ignore[arg-type]
                        from_name="A",
                        to_name="B",
                        type=rel_type,
                        change="新建",
                        evidence="证据",
                    )
                ]
            )

            snapshots = _convert_to_snapshots(result, "test-model")

            self.assertEqual(len(snapshots), 2, f"类型 {rel_type} 应生成反向边")

    def test_directed_relation_no_reverse(self) -> None:
        """有向关系不生成反向边"""
        result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据",
                )
            ]
        )

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].directionality, "directed")

    def test_empty_relations_returns_empty_list(self) -> None:
        """空关系列表返回空列表"""
        result = RelationExtractionResult(relations=[])

        snapshots = _convert_to_snapshots(result, "test-model")

        self.assertEqual(len(snapshots), 0)


class TestAnnotateChunkPhase4(unittest.TestCase):
    """
    测试 Phase4 主函数

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: phase4-code-review-fix
    """

    def test_empty_text_returns_empty_list(self) -> None:
        """空文本返回空列表"""
        mock_client = MagicMock()
        result = annotate_chunk_phase4(mock_client, "", ["张三"])
        self.assertEqual(result, [])

    def test_none_text_returns_empty_list(self) -> None:
        """None 文本返回空列表"""
        mock_client = MagicMock()
        result = annotate_chunk_phase4(mock_client, None, ["张三"])  # type: ignore[arg-type]
        self.assertEqual(result, [])

    def test_empty_characters_returns_empty_list(self) -> None:
        """空人物列表返回空列表"""
        mock_client = MagicMock()
        result = annotate_chunk_phase4(mock_client, "文本内容", [])
        self.assertEqual(result, [])

    def test_none_characters_returns_empty_list(self) -> None:
        """None 人物列表返回空列表"""
        mock_client = MagicMock()
        result = annotate_chunk_phase4(mock_client, "文本内容", None)
        self.assertEqual(result, [])

    @patch("src.models.local.annotation.phase4.settings")
    def test_successful_annotation(self, mock_settings: MagicMock) -> None:
        """成功调用关系抽取"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "{chunk_text}\n{known_characters}"

        mock_client = MagicMock()
        mock_client._config.model = "test-model"
        mock_client._is_cloud_api.return_value = False

        mock_result = RelationExtractionResult(
            relations=[
                RelationRecord(  # type: ignore[arg-type]
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据",
                )
            ]
        )
        mock_response = MagicMock()
        mock_response.thinking_content = None

        mock_client._call_annotation_api.return_value = (mock_result, mock_response)

        with patch("src.models.local.annotation.phase4.record_model_interaction"):
            result = annotate_chunk_phase4(
                mock_client, "张三打了李四", ["张三", "李四"], chunk_id=1, run_id="test-run"
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].from_name, "张三")
        self.assertEqual(result[0].to_name, "李四")


class TestConstantsConsistency(unittest.TestCase):
    """
    测试常量一致性

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: phase4-code-review-fix
    """

    def test_valid_relation_types_not_empty(self) -> None:
        """有效关系类型不为空"""
        self.assertGreater(len(VALID_RELATION_TYPES), 0)

    def test_valid_change_types_not_empty(self) -> None:
        """有效变化类型不为空"""
        self.assertGreater(len(VALID_CHANGE_TYPES), 0)

    def test_symmetric_types_subset_of_valid_types(self) -> None:
        """对称类型是有效类型的子集"""
        for rel_type in SYMMETRIC_RELATION_TYPES:
            self.assertIn(rel_type, VALID_RELATION_TYPES)

    def test_change_types_include_no_change(self) -> None:
        """变化类型包含'无变化'"""
        self.assertIn("无变化", VALID_CHANGE_TYPES)

    def test_change_types_include_all_required(self) -> None:
        """变化类型包含所有必需值"""
        required = {"无变化", "新建", "强化", "弱化", "断裂"}
        self.assertEqual(VALID_CHANGE_TYPES, required)


class TestPhase4MaxRetriesExceededError(unittest.TestCase):
    """
    测试 Phase4 异常类

    创建时间: 2026-04-05
    创建者: TraeAI
    任务: phase4-code-review-fix
    """

    def test_exception_is_exception(self) -> None:
        """异常类继承自 Exception"""
        self.assertTrue(issubclass(Phase4MaxRetriesExceededError, Exception))

    def test_exception_message(self) -> None:
        """异常消息正确"""
        error = Phase4MaxRetriesExceededError("test message")
        self.assertEqual(str(error), "test message")

    def test_exception_can_be_raised(self) -> None:
        """异常可以被抛出"""
        with self.assertRaises(Phase4MaxRetriesExceededError):
            raise Phase4MaxRetriesExceededError()


if __name__ == "__main__":
    unittest.main()
