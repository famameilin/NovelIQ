"""
创建时间: 2026-04-05
任务: phase4-code-review-fix
说明: 测试 Phase4 关系抽取功能
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config.constants import SYMMETRIC_RELATION_TYPES, VALID_CHANGE_TYPES, VALID_RELATION_TYPES
from src.models.local.annotation.evidence_renderer import render_relation_extraction_evidence_sections
from src.models.local.annotation.phase4 import (
    Phase4MaxRetriesExceededError,
    _build_phase4_messages,
    _convert_to_snapshots,
    annotate_chunk_phase4,
)
from src.models.local.schema import RelationExtractionResult, RelationRecord
from src.rag import (
    AliasMapping,
    CanonicalEntity,
    ConfirmedRelation,
    EntityTypeFact,
    EvidenceBundle,
    EvidenceItem,
    Level1AuthoritySnapshot,
)


def make_relation_record(
    from_name: str,
    to_name: str,
    type: str,
    change: str,
    evidence: str,
) -> RelationRecord:
    """创建 RelationRecord 实例，使用 alias 名称避免 Python 关键字冲突"""
    return RelationRecord.model_validate(
        {
            "from": from_name,
            "to": to_name,
            "type": type,
            "change": change,
            "evidence": evidence,
        }
    )


def build_phase4_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        structured_evidence=[
            EvidenceItem(
                evidence_type="alias_mapping",
                source="level1",
                content="灰衣人 -> 白芷",
                metadata={"alias": "灰衣人", "canonical": "白芷"},
            ),
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content="白芷",
                metadata={"name": "白芷", "entity_type": "character"},
            ),
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content="白芷<盟友>侯飞白",
                metadata={
                    "from_name": "白芷",
                    "to_name": "侯飞白",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            ),
            EvidenceItem(
                evidence_type="entity_type",
                source="level1",
                content="白芷:character",
                metadata={"name": "白芷", "entity_type": "character"},
            ),
        ],
        local_evidence=[
            EvidenceItem(
                evidence_type="active_entity",
                source="level2",
                content="白芷",
                metadata={
                    "name": "白芷",
                    "role": "主体",
                    "recent_action": "试探侯飞白",
                    "recent_emotion": "警惕",
                    "last_seen_chunk": 18,
                },
            ),
            EvidenceItem(
                evidence_type="disambig_candidate",
                source="level2",
                content="「灰衣人」可能是：白芷",
            ),
        ],
        semantic_evidence=[
            EvidenceItem(
                evidence_type="semantic_recall",
                source="level3",
                content="灰衣人曾在旧宅与侯飞白短暂结盟。",
                metadata={
                    "chunk_id": 9,
                    "similarity": 0.93,
                    "text": "灰衣人曾在旧宅与侯飞白短暂结盟。",
                },
            )
        ],
        requested_names=["灰衣人"],
        reference_slots=["POV_SLOT_C18_我"],
        level1_snapshot=Level1AuthoritySnapshot(
            alias_mappings=[AliasMapping(alias="灰衣人", canonical="白芷")],
            canonical_entities=[CanonicalEntity(name="白芷", entity_type="character")],
            confirmed_relations=[ConfirmedRelation(from_name="白芷", to_name="侯飞白", relation_type="盟友")],
            entity_types=[EntityTypeFact(name="白芷", entity_type="character")],
        ),
    )


def build_phase4_overflow_bundle() -> EvidenceBundle:
    structured = [
        EvidenceItem(
            evidence_type="alias_mapping",
            source="level1",
            content=f"代称{i} -> 角色{i}",
            metadata={"alias": f"代称{i}", "canonical": f"角色{i}"},
        )
        for i in range(1, 4)
    ]
    structured.extend(
        [
            EvidenceItem(
                evidence_type="canonical_entity",
                source="level1",
                content=f"角色{i}",
                metadata={"name": f"角色{i}", "entity_type": "character"},
            )
            for i in range(1, 4)
        ]
    )
    structured.extend(
        [
            EvidenceItem(
                evidence_type="confirmed_relation",
                source="level1",
                content=f"角色{i}<盟友>角色{i + 1}",
                metadata={
                    "from_name": f"角色{i}",
                    "to_name": f"角色{i + 1}",
                    "relation_type": "盟友",
                    "is_active": True,
                },
            )
            for i in range(1, 5)
        ]
    )

    local = [
        EvidenceItem(
            evidence_type="active_entity",
            source="level2",
            content=f"角色{i}",
            metadata={
                "name": f"角色{i}",
                "role": "主体",
                "recent_action": f"动作{i}",
                "recent_emotion": f"情绪{i}",
                "last_seen_chunk": 30 - i,
            },
        )
        for i in range(1, 6)
    ]
    local.append(
        EvidenceItem(
            evidence_type="disambig_candidate",
            source="level2",
            content="「代称1」可能是：角色1",
        )
    )

    semantic = [
        EvidenceItem(
            evidence_type="semantic_recall",
            source="level3",
            content=f"角色{i}旧场景：" + ("乙" * 180),
            metadata={
                "chunk_id": i,
                "similarity": 0.95 - i * 0.01,
                "text": f"角色{i}旧场景：" + ("乙" * 180),
            },
        )
        for i in range(1, 4)
    ]

    return EvidenceBundle(
        structured_evidence=structured,
        local_evidence=local,
        semantic_evidence=semantic,
        requested_names=["代称1"],
    )


class TestRenderRelationExtractionEvidenceSections(unittest.TestCase):
    def test_relation_extraction_sections_only_use_level1_level2_level3_main_sections(self) -> None:
        bundle = build_phase4_bundle()

        sections = render_relation_extraction_evidence_sections(bundle)
        combined = "\n\n".join(sections)

        self.assertEqual(len(sections), 4)
        self.assertIn("<Narrative_Evidence_Level1>", combined)
        self.assertIn("【近期活跃角色】", combined)
        self.assertIn("<Local_Reference_Slots>", combined)
        self.assertIn("<Vector_Evidence>", combined)
        self.assertNotIn("<Disambig_Candidates>", combined)
        self.assertNotIn("<Structured_Evidence>", combined)

    def test_relation_extraction_sections_trim_level1_active_and_vector_noise(self) -> None:
        sections = render_relation_extraction_evidence_sections(build_phase4_overflow_bundle())
        combined = "\n\n".join(sections)

        level1_section = next(section for section in sections if "<Narrative_Evidence_Level1>" in section)
        active_section = next(section for section in sections if "【近期活跃角色】" in section)
        vector_section = next(section for section in sections if "<Vector_Evidence>" in section)

        self.assertEqual(sum(1 for line in level1_section.splitlines() if line.startswith("- ")), 7)
        self.assertNotIn("已确认别名：", level1_section)
        self.assertEqual(sum(1 for line in level1_section.splitlines() if "已确认关系：" in line), 4)
        self.assertIn("已确认关系：角色4 -盟友-> 角色5", level1_section)
        self.assertEqual(sum(1 for line in active_section.splitlines() if line.startswith("- ")), 4)
        self.assertEqual(vector_section.count("[Chunk "), 2)
        self.assertNotIn("[Chunk 3]", vector_section)
        self.assertIn("...", vector_section)
        self.assertNotIn("角色1旧场景：" + ("乙" * 180), vector_section)
        self.assertNotIn("<Disambig_Candidates>", combined)


class TestBuildPhase4Messages(unittest.TestCase):
    """
    测试 Phase4 消息构建

    创建时间: 2026-04-05
    任务: phase4-code-review-fix
    """

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_success(self, mock_settings: MagicMock) -> None:
        """成功构建消息"""
        mock_settings.prompts.phase4.system = "你是关系抽取专家"
        mock_settings.prompts.phase4.user_template = "文本：${chunk_text}\n人物：${known_characters}"

        messages = _build_phase4_messages("张三打了李四", ["张三", "李四"])

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "你是关系抽取专家")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("张三、李四", messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_appends_relation_extraction_evidence_sections(self, mock_settings: MagicMock) -> None:
        """共享 evidence section 会被追加到 Phase4 prompt。"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "文本：${chunk_text}\n人物：${known_characters}"

        messages = _build_phase4_messages(
            "灰衣人看向侯飞白。",
            ["白芷", "侯飞白"],
            evidence_sections=render_relation_extraction_evidence_sections(build_phase4_bundle()),
        )

        self.assertIn("<Narrative_Evidence_Level1>", messages[1]["content"])
        self.assertIn("【近期活跃角色】", messages[1]["content"])
        self.assertIn("<Local_Reference_Slots>", messages[1]["content"])
        self.assertIn("<Vector_Evidence>", messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_with_no_characters(self, mock_settings: MagicMock) -> None:
        """无人物列表时显示'无'"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}\n${reference_slots}"

        messages = _build_phase4_messages("文本内容", None)

        self.assertIn("无", messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    def test_build_messages_supports_explicit_reference_slot_placeholder(self, mock_settings: MagicMock) -> None:
        """
        创建时间: 2026-04-29
        任务: Phase4 / RAG reference_slots 合同
        新建原因: Phase4 user_template 需要能显式渲染局部引用槽，允许模型直接输出 slot endpoint。
        """
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}\n${reference_slots}"

        messages = _build_phase4_messages(
            "我看向她。",
            ["汪淼"],
            reference_slots=["POV_SLOT_C1_我", "LOCAL_REF_C1_她"],
        )

        self.assertIn("POV_SLOT_C1_我、LOCAL_REF_C1_她", messages[1]["content"])

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
    任务: phase4-code-review-fix
    """

    def test_convert_single_relation(self) -> None:
        """转换单个关系"""
        result = RelationExtractionResult(
            relations=[
                make_relation_record(
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
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据1",
                ),
                make_relation_record(
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
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据1",
                ),
                make_relation_record(
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
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="家族",
                    change="新建",
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
                make_relation_record(
                    from_name="张三",
                    to_name="张三",
                    type="家族",
                    change="新建",
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
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="家族",
                    change="新建",
                    evidence="证据1",
                ),
                make_relation_record(
                    from_name="李四",
                    to_name="张三",
                    type="家族",
                    change="新建",
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
                    make_relation_record(
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
                make_relation_record(
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


class TestAnnotateChunkPhase4(unittest.IsolatedAsyncioTestCase):
    """
    测试 Phase4 主函数

    创建时间: 2026-04-05
    任务: phase4-code-review-fix
    """

    async def test_empty_text_returns_empty_list(self) -> None:
        """空文本返回空列表"""
        mock_client = MagicMock()
        result = await annotate_chunk_phase4(mock_client, "", ["张三"])
        self.assertEqual(result, [])

    async def test_none_text_returns_empty_list(self) -> None:
        """None 文本返回空列表"""
        mock_client = MagicMock()
        result = await annotate_chunk_phase4(mock_client, None, ["张三"])  # type: ignore[arg-type]
        self.assertEqual(result, [])

    async def test_empty_characters_returns_empty_list(self) -> None:
        """空人物列表返回空列表"""
        mock_client = MagicMock()
        result = await annotate_chunk_phase4(mock_client, "文本内容", [])
        self.assertEqual(result, [])

    async def test_none_characters_returns_empty_list(self) -> None:
        """None 人物列表返回空列表"""
        mock_client = MagicMock()
        result = await annotate_chunk_phase4(mock_client, "文本内容", None)
        self.assertEqual(result, [])

    @patch("src.models.local.annotation.phase4.settings")
    async def test_reference_slots_allow_phase4_without_known_characters(self, mock_settings: MagicMock) -> None:
        """
        创建时间: 2026-04-29
        任务: Phase4 / RAG reference_slots 合同
        新建原因: 当前片段只有局部引用位时，Phase4 仍应运行并看到 slot section，而不是被空 known_characters 直接短路。
        """
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}"
        mock_settings.runtime.annotation.phase_max_retries = 3

        mock_client = MagicMock()
        mock_client._config.model = "test-model"
        mock_client._config.thinking_enabled = False
        mock_client._is_cloud_api.return_value = False
        mock_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))
        mock_client._session = None
        mock_client._call_annotation_api = AsyncMock(return_value=(RelationExtractionResult(relations=[]), MagicMock()))

        with patch("src.models.local.annotation.runtime.record_model_interaction"):
            result = await annotate_chunk_phase4(
                mock_client,
                "我看向她。",
                None,
                reference_slots=["POV_SLOT_C1_我", "LOCAL_REF_C1_她"],
                evidence_bundle=EvidenceBundle(reference_slots=["POV_SLOT_C1_我", "LOCAL_REF_C1_她"]),
            )

        self.assertEqual(result, [])
        call_messages = mock_client._call_annotation_api.await_args.kwargs["messages"]
        self.assertIn("<Local_Reference_Slots>", call_messages[1]["content"])
        self.assertIn("POV_SLOT_C1_我", call_messages[1]["content"])
        self.assertIn("LOCAL_REF_C1_她", call_messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    async def test_successful_annotation(self, mock_settings: MagicMock) -> None:
        """成功调用关系抽取"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}"

        mock_client = MagicMock()
        mock_client._config.model = "test-model"
        mock_client._config.thinking_enabled = True
        mock_client._is_cloud_api.return_value = False
        mock_client._extract_reasoning_tokens.return_value = 31
        mock_client._record_estimated_token_usage_from_messages = MagicMock()
        mock_client._process_annotation_response.return_value = (
            '{"relations": []}',
            "phase4 thinking",
            MagicMock(),
        )

        mock_result = RelationExtractionResult(
            relations=[
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据",
                )
            ]
        )
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='{"relations": []}', reasoning_content="phase4 thinking"))
        ]

        mock_client._call_annotation_api = AsyncMock(return_value=(mock_result, mock_response))

        with patch("src.models.local.annotation.runtime.record_model_interaction") as mock_record_model_interaction:
            result = await annotate_chunk_phase4(
                mock_client,
                "张三打了李四",
                ["张三", "李四"],
                chunk_id=1,
                run_id="test-run",
                evidence_bundle=build_phase4_bundle(),
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].from_name, "张三")
        self.assertEqual(result[0].to_name, "李四")
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["thinking_content"], "phase4 thinking")
        self.assertEqual(mock_record_model_interaction.call_args.kwargs["reasoning_tokens"], 31)
        self.assertTrue(mock_record_model_interaction.call_args.kwargs["requested_thinking"])
        mock_client._record_estimated_token_usage_from_messages.assert_called_once()
        assert mock_client._record_estimated_token_usage_from_messages.call_args.args[2] == "phase4"
        call_messages = mock_client._call_annotation_api.await_args.kwargs["messages"]
        self.assertIn("张三、李四", call_messages[1]["content"])
        self.assertIn("<Narrative_Evidence_Level1>", call_messages[1]["content"])
        self.assertIn("【近期活跃角色】", call_messages[1]["content"])
        self.assertIn("<Vector_Evidence>", call_messages[1]["content"])

    @patch("src.models.local.annotation.phase4.settings")
    async def test_annotation_with_empty_bundle_falls_back_to_original_prompt_shape(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """空 bundle 不报错，并回退到无 evidence section 的旧 prompt 形状。"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}"
        mock_settings.runtime.annotation.phase_max_retries = 3

        mock_client = MagicMock()
        mock_client._config.model = "test-model"
        mock_client._config.thinking_enabled = False
        mock_client._is_cloud_api.return_value = False
        mock_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))
        mock_client._session = None
        mock_client._call_annotation_api = AsyncMock(return_value=(RelationExtractionResult(relations=[]), MagicMock()))

        with patch("src.models.local.annotation.runtime.record_model_interaction"):
            result = await annotate_chunk_phase4(
                mock_client,
                "白芷看向侯飞白。",
                ["白芷", "侯飞白"],
                evidence_bundle=EvidenceBundle(),
            )

        self.assertEqual(result, [])
        call_messages = mock_client._call_annotation_api.await_args.kwargs["messages"]
        self.assertEqual(call_messages[1]["content"], "白芷看向侯飞白。\n白芷、侯飞白")
        self.assertNotIn("<Narrative_Evidence_Level1>", call_messages[1]["content"])
        self.assertNotIn("【近期活跃角色】", call_messages[1]["content"])
        self.assertNotIn("<Vector_Evidence>", call_messages[1]["content"])

    @patch("src.models.local.annotation.runtime.record_model_interaction")
    @patch("src.models.local.annotation.phase4.settings")
    async def test_phase4_uses_fallback_client_after_primary_retries(
        self,
        mock_settings: MagicMock,
        _mock_record_model_interaction: MagicMock,
    ) -> None:
        """Phase4 主客户端失败后会切到 fallback_client。"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}"
        mock_settings.runtime.annotation.phase_max_retries = 3

        primary_client = MagicMock()
        primary_client._config.model = "primary-model"
        primary_client._config.thinking_enabled = False
        primary_client._is_cloud_api.return_value = False
        primary_client._session = None
        primary_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))

        fallback_client = MagicMock()
        fallback_client._config.model = "fallback-model"
        fallback_client._config.thinking_enabled = False
        fallback_client._is_cloud_api.return_value = True
        fallback_client._session = None
        fallback_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))

        primary_calls = 0
        fallback_calls = 0
        parsed = RelationExtractionResult(
            relations=[
                make_relation_record(
                    from_name="张三",
                    to_name="李四",
                    type="敌对",
                    change="新建",
                    evidence="证据",
                )
            ]
        )
        response = MagicMock()

        async def primary_call(*args, **kwargs):
            nonlocal primary_calls
            primary_calls += 1
            raise ConnectionError("primary failed")

        async def fallback_call(*args, **kwargs):
            nonlocal fallback_calls
            fallback_calls += 1
            return parsed, response

        primary_client._call_annotation_api = AsyncMock(side_effect=primary_call)
        fallback_client._call_annotation_api = AsyncMock(side_effect=fallback_call)

        result = await annotate_chunk_phase4(
            primary_client,
            "张三打了李四",
            ["张三", "李四"],
            fallback_client=fallback_client,
        )

        self.assertEqual(primary_calls, 3)
        self.assertEqual(fallback_calls, 1)
        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0].from_name, "张三")
        self.assertEqual(result[0].to_name, "李四")

    @patch("src.models.local.annotation.phase4.settings")
    async def test_phase4_retries_exhausted_raises_error(self, mock_settings: MagicMock) -> None:
        """Phase4 主客户端和兜底客户端都失败时应抛错。"""
        mock_settings.prompts.phase4.system = "system"
        mock_settings.prompts.phase4.user_template = "${chunk_text}\n${known_characters}"
        mock_settings.runtime.annotation.phase_max_retries = 3

        primary_client = MagicMock()
        primary_client._config.model = "primary-model"
        primary_client._config.thinking_enabled = False
        primary_client._is_cloud_api.return_value = False
        primary_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))

        fallback_client = MagicMock()
        fallback_client._config.model = "fallback-model"
        fallback_client._config.thinking_enabled = False
        fallback_client._is_cloud_api.return_value = True
        fallback_client._process_annotation_response = MagicMock(return_value=('{"relations": []}', None, None))

        primary_client._call_annotation_api = AsyncMock(side_effect=ConnectionError("primary failed"))
        fallback_client._call_annotation_api = AsyncMock(side_effect=ConnectionError("fallback failed"))

        with self.assertRaises(Phase4MaxRetriesExceededError):
            await annotate_chunk_phase4(
                primary_client,
                "张三打了李四",
                ["张三", "李四"],
                fallback_client=fallback_client,
            )


class TestConstantsConsistency(unittest.TestCase):
    """
    测试常量一致性

    创建时间: 2026-04-05
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

    def test_change_types_include_all_required(self) -> None:
        """变化类型包含所有必需值"""
        required = {"新建", "强化", "弱化", "断裂"}
        self.assertEqual(VALID_CHANGE_TYPES, required)


class TestPhase4MaxRetriesExceededError(unittest.TestCase):
    """
    测试 Phase4 异常类

    创建时间: 2026-04-05
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
