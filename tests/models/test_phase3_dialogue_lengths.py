"""
Phase3 对话长度与后处理验证测试

创建时间: 2026-04-23
任务: 复杂度与耦合审查 P2 - 测试工程化
说明: 从 test_phase3.py 拆出长度聚合、thinking 参数和 speaker 后处理场景。

修改时间: 2026-04-26
修改者: Codex
任务: phase3-proof-only-fastpath-batch10
修改内容: 补齐 Phase3 新批处理实现需要的 mock 配置，避免旧测试因 settings 桩不完整而失真。
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.local.annotation.phase3 import attribute_dialogues_with_llm, compute_dialogue_lengths_with_llm
from src.models.local.schema import DialogueRecord, QuoteCandidate


class TestComputeDialogueLengthsWithLLM(unittest.IsolatedAsyncioTestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试计算对话长度功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配新的返回格式
    """

    async def test_empty_text_returns_empty_result(self) -> None:
        """空文本返回空结果对象"""
        mock_client = MagicMock()
        result = await compute_dialogue_lengths_with_llm(mock_client, "")
        self.assertEqual(result.speaker_lengths, {})
        self.assertEqual(result.canonical_attribution, {})
        self.assertEqual(result.dialogues, [])

    async def test_no_dialogues_returns_empty_result(self) -> None:
        """没有对话返回空结果对象"""
        mock_client = MagicMock()
        result = await compute_dialogue_lengths_with_llm(mock_client, "没有对话的文本")
        self.assertEqual(result.speaker_lengths, {})
        self.assertEqual(result.canonical_attribution, {})
        self.assertEqual(result.dialogues, [])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_compute_lengths_with_attribution(self, mock_attribute: MagicMock) -> None:
        """根据归属结果计算对话长度 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker=["李四"]),
            DialogueRecord(index=3, content="再见", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。\u201c再见\u201d他说。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertIsInstance(result.speaker_lengths, dict)
        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好") + len("再见"))
        self.assertEqual(result.speaker_lengths.get("李四", 0), len("你好啊"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"], 2: ["李四"], 3: ["张三"]})
        self.assertEqual(result.dialogues, [(1, "你好"), (2, "你好啊"), (3, "再见")])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_unknown_speaker_kept_and_counted(self, mock_settings: MagicMock) -> None:
        """未知说话者会被保留并计入长度，交由下游继续判断。

        此测试走端到端真实分支：传入 known_characters，mock API 返回不在已知列表中的 speaker，
        验证 _post_process_validation 不丢弃未知 speaker，且长度统计正确。
        """
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
                DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker=["王五"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。"

        result = await compute_dialogue_lengths_with_llm(
            mock_annotation_client,
            text,
            known_characters=["张三"],
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.speaker_lengths.get("王五", 0), len("你好啊"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"], 2: ["王五"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_non_dialogue_filtered(self, mock_attribute: MagicMock) -> None:
        """非对话内容被过滤 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="精打细算", is_dialogue=False, speaker=None),
            DialogueRecord(index=2, content="你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c精打细算\u201d的折扇。\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(len(result.dialogues), 1)
        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.canonical_attribution, {2: ["张三"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_source_content_preferred_over_model_content(self, mock_attribute: MagicMock) -> None:
        """长度统计优先使用原文提取内容，避免模型改写影响"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好你好你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.dialogues, [(1, "你好")])
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_duplicate_index_counted_once(self, mock_attribute: MagicMock) -> None:
        """重复 index 只计一次，避免长度膨胀"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        result = await compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(result.speaker_lengths.get("张三", 0), len("你好"))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogues, [(1, "你好")])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_return_tones_when_requested(self, mock_attribute: MagicMock) -> None:
        """显式请求时返回对话语气。"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"], tone="强硬"),
        ]

        mock_client = MagicMock()
        text = '"你好"他说道。'

        result = await compute_dialogue_lengths_with_llm(
            mock_client,
            text,
            return_tones=True,
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len(result.dialogues[0][1]))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogues[0][0], 1)
        self.assertEqual(result.dialogue_tones, {1: "强硬"})

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    async def test_return_identity_clues_when_requested(self, mock_attribute: MagicMock) -> None:
        """显式请求时返回身份线索。"""
        mock_attribute.return_value = [
            DialogueRecord(
                index=1,
                content="你好",
                is_dialogue=True,
                speaker=["张三"],
                identity_clue="声音低沉的中年男子",
            ),
        ]

        mock_client = MagicMock()
        text = '"你好"他说道。'

        result = await compute_dialogue_lengths_with_llm(
            mock_client,
            text,
            return_identity_clues=True,
        )

        self.assertEqual(result.speaker_lengths.get("张三", 0), len(result.dialogues[0][1]))
        self.assertEqual(result.canonical_attribution, {1: ["张三"]})
        self.assertEqual(result.dialogue_identity_clues, {1: "声音低沉的中年男子"})

    @patch("src.models.local.annotation.phase3.settings")
    async def test_thinking_enabled_false_is_passed_to_api(self, mock_settings: MagicMock) -> None:
        """验证 thinking_enabled=False 时 enable_thinking=False 被传递给 API 调用。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = False
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
        )

        call_kwargs = mock_annotation_client._call_annotation_api.await_args.kwargs
        self.assertFalse(call_kwargs["enable_thinking"])

    @patch("src.models.local.annotation.phase3.settings")
    async def test_thinking_enabled_true_is_passed_to_api(self, mock_settings: MagicMock) -> None:
        """验证 thinking_enabled=True 时 enable_thinking=True 被传递给 API 调用。"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"
        mock_settings.thinking.phase3_candidates_per_batch = 8
        mock_settings.thinking.phase3_batch_parallelism = 1
        mock_settings.runtime.annotation.phase3_max_retries = 3

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.thinking_enabled = True
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["张三"]),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api = AsyncMock(return_value=(mock_response, "{}"))

        await attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            [QuoteCandidate(index=1, content="你好")],
            known_characters=["张三"],
        )

        call_kwargs = mock_annotation_client._call_annotation_api.await_args.kwargs
        self.assertTrue(call_kwargs["enable_thinking"])


class TestPostProcessValidationFix(unittest.TestCase):
    """测试 _post_process_validation：别名归一化 + 保留 LLM speaker 判断"""

    def _call_validation(
        self,
        records: list[DialogueRecord],
        known_characters: list[str] | None = None,
        alias_map: dict[str, str] | None = None,
    ) -> list[DialogueRecord]:
        from src.models.local.annotation.phase3 import _post_process_validation

        candidates = [QuoteCandidate(index=r.index, content=r.content or "") for r in records]
        return _post_process_validation(records, candidates, known_characters, alias_map, chunk_id=1)

    def test_speaker_in_known_set_passes_through(self) -> None:
        """speaker 在 known_set 中时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])

    def test_unknown_speaker_kept(self) -> None:
        """speaker 不在 known_set 中时保留 LLM 原始判断，不丢弃不修正"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["新角色"]),
        ]
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["新角色"])

    def test_alias_normalized(self) -> None:
        """别名归一化"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["猴子"]),
        ]
        result = self._call_validation(records, known_characters=["侯飞白"], alias_map={"猴子": "侯飞白"})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["侯飞白"])

    def test_no_known_characters_passes_through(self) -> None:
        """无 known_characters 时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        result = self._call_validation(records, known_characters=None)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])

    def test_identity_clue_preserved(self) -> None:
        """identity_clue 作为元数据保留，不参与 speaker 修正"""
        records = [
            DialogueRecord(
                index=1,
                content="我叫白芷。",
                is_dialogue=True,
                speaker=["白芷"],
                identity_clue="白芷自称名为白芷",
            ),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, ["白芷"])
        self.assertEqual(result[0].identity_clue, "白芷自称名为白芷")

    def test_null_speaker_passes_through(self) -> None:
        """speaker 为 null 时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker=None),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].speaker)

    def test_invalid_index_skipped(self) -> None:
        """无效 index 的记录被跳过"""
        from src.models.local.annotation.phase3 import _post_process_validation

        records = [
            DialogueRecord(index=99, content="你好", is_dialogue=True, speaker=["白芷"]),
        ]
        candidates = [QuoteCandidate(index=1, content="你好")]
        result = _post_process_validation(records, candidates, ["白芷"], None, chunk_id=1)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
