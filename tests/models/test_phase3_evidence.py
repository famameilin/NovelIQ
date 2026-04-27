"""
Phase3 对话归属 evidence 集成测试

创建时间: 2026-04-23
任务: 复杂度与耦合审查 P2 - 测试工程化
说明: 从 test_phase3.py 拆出 evidence bundle 渲染与传递场景。
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.local.annotation.evidence_renderer import render_dialogue_attribution_evidence_sections
from src.models.local.annotation.phase3 import attribute_dialogues_with_llm, compute_dialogue_lengths_with_llm
from src.models.local.schema import QuoteCandidate
from tests.support.phase3_factories import (
    build_phase3_bundle as _build_phase3_bundle,
)
from tests.support.phase3_factories import (
    build_phase3_overflow_bundle as _build_phase3_overflow_bundle,
)
from tests.support.phase3_factories import (
    build_phase3_priority_bundle as _build_phase3_priority_bundle,
)


class TestPhase3EvidenceIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_attribute_dialogues_with_llm_appends_shared_evidence_blocks(self) -> None:
        bundle = _build_phase3_bundle()

        with patch("src.models.local.annotation.phase3.settings") as mock_settings:
            mock_settings.prompts.phase3.system = "system"
            mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
            mock_settings.thinking.phase3_candidates_per_batch = 8
            mock_settings.thinking.phase3_batch_parallelism = 1
            mock_settings.runtime.annotation.phase3_max_retries = 3

            mock_annotation_client = MagicMock()
            mock_annotation_client._config.model = "test-model"
            mock_annotation_client._config.thinking_enabled = False
            mock_annotation_client._is_cloud_api.return_value = False
            mock_response = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
            mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

            await attribute_dialogues_with_llm(
                mock_annotation_client,
                "“你终于来了。”",
                [QuoteCandidate(index=1, content="你终于来了。")],
                known_characters=["白芷"],
                evidence_bundle=bundle,
            )

        user_prompt = mock_annotation_client._call_annotation_api.await_args.kwargs["messages"][-1]["content"]
        self.assertIn("【近期活跃角色】", user_prompt)
        self.assertIn("<Narrative_Evidence_Level1>", user_prompt)
        self.assertIn("<Disambig_Candidates>", user_prompt)
        self.assertIn("<Vector_Evidence>", user_prompt)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_compute_dialogue_lengths_passes_evidence_bundle_to_phase3(self, mock_attribute: MagicMock) -> None:
        bundle = _build_phase3_bundle()
        mock_attribute.return_value = []

        mock_client = MagicMock()
        await compute_dialogue_lengths_with_llm(
            mock_client,
            "“你好”他说道。",
            evidence_bundle=bundle,
        )

        self.assertIs(mock_attribute.await_args.kwargs["evidence_bundle"], bundle)

    @patch("src.models.local.annotation.phase3.settings")
    async def test_attribute_dialogues_with_llm_prioritizes_batch_relevant_candidates(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """Phase3 会优先保留当前 batch 真正提到的候选名，而不是机械截前两条。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._is_cloud_api.return_value = False
        mock_response = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "“别名三，你终于开口了。”",
            [QuoteCandidate(index=1, content="别名三，你终于开口了。")],
            known_characters=["人物一", "人物二", "人物三"],
            evidence_bundle=_build_phase3_priority_bundle(),
        )

        user_prompt = mock_annotation_client._call_annotation_api.await_args.kwargs["messages"][-1]["content"]
        self.assertIn("「别名三」可能是：人物一、人物二、人物三", user_prompt)
        self.assertLess(
            user_prompt.index("「别名三」可能是：人物一、人物二、人物三"),
            user_prompt.index("「别名一」可能是：人物一、人物二、人物三"),
        )

    @patch("src.models.local.annotation.phase3.settings")
    async def test_attribute_dialogues_with_llm_recomputes_priority_names_per_batch(
        self,
        mock_settings: MagicMock,
    ) -> None:
        """跨 batch 时，每个 batch 都应按自己的候选内容重算 priority candidate names。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 1
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._is_cloud_api.return_value = False
        mock_response = MagicMock(dialogues=[], model_dump=MagicMock(return_value={}))
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "“别名一，你来了。”\n“别名三，你终于开口了。”",
            [
                QuoteCandidate(index=1, content="别名一，你来了。"),
                QuoteCandidate(index=2, content="别名三，你终于开口了。"),
            ],
            known_characters=["人物一", "人物二", "人物三"],
            evidence_bundle=_build_phase3_priority_bundle(),
        )

        first_prompt = mock_annotation_client._call_annotation_api.await_args_list[0].kwargs["messages"][-1]["content"]
        second_prompt = mock_annotation_client._call_annotation_api.await_args_list[1].kwargs["messages"][-1]["content"]
        self.assertIn("「别名一」可能是：人物一、人物二、人物三", first_prompt)
        self.assertNotIn("「别名三」可能是：人物一、人物二、人物三", first_prompt)
        self.assertIn("「别名三」可能是：人物一、人物二、人物三", second_prompt)
        self.assertLess(
            second_prompt.index("「别名三」可能是：人物一、人物二、人物三"),
            second_prompt.index("「别名一」可能是：人物一、人物二、人物三"),
        )


class TestRenderDialogueAttributionEvidenceSections(unittest.TestCase):
    """测试 Phase3 renderer 的 alias_map 和 active_entities 逻辑"""

    def _call(self, bundle=None, alias_map=None, active_entities=None):
        return render_dialogue_attribution_evidence_sections(
            bundle,
            alias_map=alias_map,
            active_entities=active_entities,
        )

    def test_both_none_returns_empty(self) -> None:
        """evidence_bundle=None 且 active_entities=None 时返回 []"""
        result = self._call()
        self.assertEqual(result, [])

    def test_alias_map_none_includes_level1_aliases(self) -> None:
        """alias_map=None 时 include_level1_alias_mappings=True，prompt 包含 Level1 别名裁决"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map=None)
        # 应包含 Level1 别名映射行
        self.assertTrue(any("已确认别名：灰衣人" in s for s in result))

    def test_alias_map_provided_excludes_level1_aliases(self) -> None:
        """alias_map 非 None 时 include_level1_alias_mappings=False，不注入 Level1 别名裁决"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map={"猴子": "侯飞白"})
        # disambig_context 是合并块（Level1 事实 + Level2 候选 + Level3 向量），
        # include_level1_alias_mappings=False 只是不包含别名映射行，
        # 但仍会包含 disambig candidates。因此检查“已确认别名：灰衣人”不在结果中。
        self.assertTrue(all("已确认别名：灰衣人" not in s for s in result))
        # 但 active_entities 仍应存在
        self.assertTrue(any("【近期活跃角色】" in s for s in result))

    def test_active_entities_override_bundle(self) -> None:
        """active_entities 非 None 时优先使用传入值，而非 bundle 中的值"""
        bundle = _build_phase3_bundle()
        custom_entities = "【近期活跃角色】自定义实体"
        result = self._call(bundle=bundle, active_entities=custom_entities)
        self.assertIn(custom_entities, result)

    def test_explicit_active_entities_string_is_trimmed_by_phase3_policy(self) -> None:
        """真实入口传入的 active_entities 字符串也要经过 Phase3 裁剪。"""
        custom_entities = "\n".join(
            [
                "【近期活跃角色】",
                "- 角色一（speaker_candidate）：动作一 [chunk=1]",
                "- 角色二（speaker_candidate）：动作二 [chunk=2]",
                "- 角色三（speaker_candidate）：动作三 [chunk=3]",
                "- 角色四（speaker_candidate）：动作四 [chunk=4]",
            ]
        )

        result = self._call(bundle=_build_phase3_bundle(), active_entities=custom_entities)
        active_section = next(section for section in result if "【近期活跃角色】" in section)

        self.assertEqual(sum(1 for line in active_section.splitlines() if line.startswith("- ")), 3)
        self.assertNotIn("角色四", active_section)

    def test_active_entities_without_bundle(self) -> None:
        """evidence_bundle=None 但 active_entities 非 None 时，只返回 active_entities"""
        custom_entities = "【近期活跃角色】仅 fallback"
        result = self._call(bundle=None, active_entities=custom_entities)
        self.assertEqual(result, [custom_entities])

    def test_explicit_empty_alias_map_still_suppresses_level1_alias_lines(self) -> None:
        """显式 alias_map={} 时仍视为调用方已决议，不再反向注入 Level1 alias。"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, alias_map={})
        self.assertTrue(all("已确认别名：灰衣人" not in s for s in result))

    def test_explicit_empty_active_entities_suppresses_bundle_fallback(self) -> None:
        """显式传入空字符串时，不回退 bundle active_entities，也不插入空白区段。"""
        bundle = _build_phase3_bundle()
        result = self._call(bundle=bundle, active_entities="")
        self.assertTrue(all("【近期活跃角色】" not in s for s in result))

    def test_phase3_sections_trim_overlong_shared_evidence_context(self) -> None:
        """Phase3 task renderer 会裁剪过长的共享 evidence，避免 prompt 继续膨胀。"""
        result = self._call(bundle=_build_phase3_overflow_bundle())

        active_section = next(section for section in result if "【近期活跃角色】" in section)
        level1_section = next(section for section in result if "<Narrative_Evidence_Level1>" in section)
        disambig_section = next(section for section in result if "<Disambig_Candidates>" in section)
        vector_section = next(section for section in result if "<Vector_Evidence>" in section)

        self.assertEqual(sum(1 for line in active_section.splitlines() if line.startswith("- ")), 3)
        self.assertEqual(sum(1 for line in level1_section.splitlines() if line.startswith("- ")), 6)
        self.assertEqual(sum(1 for line in disambig_section.splitlines() if line.startswith("「")), 2)
        self.assertEqual(vector_section.count("[Chunk "), 2)
        self.assertNotIn("[Chunk 3]", vector_section)
        self.assertIn("...", vector_section)
        self.assertNotIn("人物1历史片段：" + ("甲" * 150), vector_section)
