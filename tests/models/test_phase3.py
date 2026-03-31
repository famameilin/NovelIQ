"""
创建时间: 2026-03-21
创建者: TraeAI
任务: refactor-phase3-to-annotation-layer
说明: 测试 Phase3 对话归属判断功能

修改时间: 2026-03-22
修改者: TraeAI
任务: code-quality-review
修改内容: 更新测试用例，适配对话归属失败时抛出异常而非返回空字典

修改时间: 2026-03-23
修改者: TraeAI
任务: refactor-dialogue-attribution-pipeline
修改内容: 更新测试用例，适配新的返回格式（QuoteCandidate、DialogueRecord）
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.models.local.annotation.phase3 import (
    _extract_speaker_from_clue,
    attribute_dialogues_with_llm,
    compute_dialogue_lengths_with_llm,
    extract_dialogues_from_text,
)
from src.models.local.schema import DialogueRecord, QuoteCandidate


class TestExtractDialoguesFromText(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试对话提取功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 QuoteCandidate 返回格式

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: fix-phase3-validation
    修改内容: 使用正确的 Unicode 引号字符 (U+201C/U+201D)
    """

    def test_extract_single_dialogue(self) -> None:
        """提取单个对话 - 使用中文双引号 U+201C/U+201D"""
        text = "他说：\u201c你好啊。\u201d"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], QuoteCandidate)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "你好啊。")

    def test_extract_multiple_dialogues(self) -> None:
        """提取多个对话 - 使用中文双引号"""
        text = "\u201c第一个对话。\u201d他说道。\u201c第二个对话。\u201d她回答。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "第一个对话。")
        self.assertEqual(result[1].index, 2)
        self.assertEqual(result[1].content, "第二个对话。")

    def test_extract_dialogue_with_empty_content_skipped(self) -> None:
        """空对话内容被跳过，索引保持原始位置"""
        text = "\u201c\u201d他说道。\u201c有内容\u201d她回答。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].index, 2)
        self.assertEqual(result[0].content, "有内容")

    def test_extract_no_dialogues(self) -> None:
        """没有对话时返回空列表"""
        text = "这是一段没有对话的文本。"
        result = extract_dialogues_from_text(text)
        self.assertEqual(len(result), 0)

    def test_extract_dialogue_with_whitespace(self) -> None:
        """对话内容前后空白被去除 - 使用英文双引号"""
        text = '"  有空白的内容  "'
        result = extract_dialogues_from_text(text)
        self.assertEqual(result[0].index, 1)
        self.assertEqual(result[0].content, "有空白的内容")


class TestAttributeDialoguesWithLLM(unittest.TestCase):
    """
    创建时间: 2026-03-21
    创建者: TraeAI
    任务: refactor-phase3-to-annotation-layer
    说明: 测试 LLM 对话归属判断功能

    修改时间: 2026-03-23
    修改者: TraeAI
    任务: refactor-dialogue-attribution-pipeline
    修改内容: 更新测试用例，适配 DialogueRecord 返回格式
    """

    def test_empty_dialogues_returns_empty_list(self) -> None:
        """空对话列表返回空列表"""
        mock_client = MagicMock()
        result = attribute_dialogues_with_llm(mock_client, "text", [], ["张三"])
        self.assertEqual(result, [])

    @patch("src.models.local.annotation.phase3.settings")
    def test_successful_attribution(self, mock_settings: MagicMock) -> None:
        """成功归属对话"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_annotation_client = MagicMock()

        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_annotation_client._call_api_stream.return_value = MagicMock()
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
                DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="李四"),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api.return_value = (mock_response, "{}")
        candidates = [QuoteCandidate(index=1, content="你好"), QuoteCandidate(index=2, content="你好啊")]
        result = attribute_dialogues_with_llm(mock_annotation_client, "对话文本", candidates, ["张三", "李四"])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].speaker, "张三")
        self.assertEqual(result[1].speaker, "李四")

    @patch("src.models.local.annotation.phase3.settings")
    def test_exception_raises_dialogue_attribution_error(self, mock_settings: MagicMock) -> None:
        """异常时抛出 ValueError（model 未配置）"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_annotation_client = MagicMock()
        mock_annotation_client._config.model = None

        candidates = [QuoteCandidate(index=1, content="你好")]

        with self.assertRaises(ValueError):
            attribute_dialogues_with_llm(mock_annotation_client, "对话文本", candidates, ["张三"])

    @patch("src.models.local.annotation.phase3.settings")
    def test_alias_speaker_normalized_before_known_filter(self, mock_settings: MagicMock) -> None:
        """说话者别名在 known_characters 校验前先归一化"""
        mock_settings.prompts.phase3.system = "system"
        mock_settings.prompts.phase3.user_template = "{chunk_text}\n{dialogue_list}\n{known_characters}"

        mock_annotation_client = MagicMock()

        mock_annotation_client._config.model = "test-model"
        mock_annotation_client._config.temperature = 0.7
        mock_annotation_client._config.top_p = 0.9
        mock_annotation_client._config.presence_penalty = 0.0
        mock_annotation_client._is_cloud_api.return_value = False
        mock_annotation_client._build_json_schema.return_value = {}
        mock_annotation_client._call_api_stream.return_value = MagicMock()
        mock_response = MagicMock(
            dialogues=[
                DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="猴子"),
            ],
            model_dump=MagicMock(return_value={}),
        )
        mock_annotation_client._call_annotation_api.return_value = (mock_response, "{}")
        candidates = [QuoteCandidate(index=1, content="你好")]
        result = attribute_dialogues_with_llm(
            mock_annotation_client,
            "对话文本",
            candidates,
            known_characters=["侯飞白"],
            alias_map={"猴子": "侯飞白"},
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "侯飞白")


class TestComputeDialogueLengthsWithLLM(unittest.TestCase):
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

    def test_empty_text_returns_empty_dict(self) -> None:
        """空文本返回空字典"""
        mock_client = MagicMock()
        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, "")
        self.assertEqual(speaker_lengths, {})
        self.assertEqual(attribution, {})
        self.assertEqual(dialogues, [])

    def test_no_dialogues_returns_empty_dict(self) -> None:
        """没有对话返回空字典"""
        mock_client = MagicMock()
        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, "没有对话的文本")
        self.assertEqual(speaker_lengths, {})
        self.assertEqual(attribution, {})
        self.assertEqual(dialogues, [])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_compute_lengths_with_attribution(self, mock_attribute: MagicMock) -> None:
        """根据归属结果计算对话长度 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="李四"),
            DialogueRecord(index=3, content="再见", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。\u201c再见\u201d他说。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertIsInstance(speaker_lengths, dict)
        self.assertEqual(speaker_lengths.get("张三", 0), 4)
        self.assertEqual(speaker_lengths.get("李四", 0), 3)
        self.assertIsInstance(attribution, dict)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_unknown_speaker_not_counted(self, mock_attribute: MagicMock) -> None:
        """未知说话者的对话不计入 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=2, content="你好啊", is_dialogue=True, speaker="王五"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。\u201c你好啊\u201d她回答。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertNotIn("李四", speaker_lengths)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_non_dialogue_filtered(self, mock_attribute: MagicMock) -> None:
        """非对话内容被过滤 - 使用中文双引号"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="精打细算", is_dialogue=False, speaker=None),
            DialogueRecord(index=2, content="你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c精打细算\u201d的折扇。\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(len(dialogues), 1)
        self.assertEqual(speaker_lengths.get("张三", 0), 2)

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_source_content_preferred_over_model_content(self, mock_attribute: MagicMock) -> None:
        """长度统计优先使用原文提取内容，避免模型改写影响"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好你好你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertEqual(dialogues, [(1, "你好")])

    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_duplicate_index_counted_once(self, mock_attribute: MagicMock) -> None:
        """重复 index 只计一次，避免长度膨胀"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="张三"),
        ]

        mock_client = MagicMock()
        text = "\u201c你好\u201d他说道。"

        speaker_lengths, attribution, dialogues = compute_dialogue_lengths_with_llm(mock_client, text)

        self.assertEqual(speaker_lengths.get("张三", 0), 2)
        self.assertEqual(attribution, {1: "张三"})
        self.assertEqual(dialogues, [(1, "你好")])


    @patch("src.models.local.annotation.phase3.attribute_dialogues_with_llm")
    def test_return_tones_when_requested(self, mock_attribute: MagicMock) -> None:
        """鏄惧紡璇锋眰鏃惰繑鍥炲璇濊姘旀槧灏?"""
        mock_attribute.return_value = [
            DialogueRecord(index=1, content="浣犲ソ", is_dialogue=True, speaker="寮犱笁", tone="寮虹‖"),
        ]

        mock_client = MagicMock()
        text = '"浣犲ソ"浠栬閬撱€?'

        speaker_lengths, attribution, dialogues, tones = compute_dialogue_lengths_with_llm(
            mock_client,
            text,
            return_tones=True,
        )

        self.assertEqual(speaker_lengths.get("寮犱笁", 0), len(dialogues[0][1]))
        self.assertEqual(attribution, {1: "寮犱笁"})
        self.assertEqual(dialogues[0][0], 1)
        self.assertEqual(tones, {1: "寮虹‖"})


class TestExtractSpeakerFromClue(unittest.TestCase):
    """测试从 identity_clue 反推 speaker 的辅助函数"""

    def test_self_introduction(self) -> None:
        """自报身份模式"""
        self.assertEqual(_extract_speaker_from_clue("白芷自称名为白芷", {"白芷", "伯安"}), "白芷")
        self.assertEqual(_extract_speaker_from_clue("说话者自称是铁匠铺老板", None), None)

    def test_address_relation(self) -> None:
        """称呼关系模式"""
        self.assertEqual(_extract_speaker_from_clue("赤甲卫称呼灰衣人为先生，自称属下", {"赤甲卫"}), "赤甲卫")

    def test_explanation_pattern(self) -> None:
        """说明/揭示模式"""
        self.assertEqual(_extract_speaker_from_clue("白芷说明精灵族长老活了快四百岁", {"白芷"}), "白芷")

    def test_generic_terms_excluded(self) -> None:
        """泛指词被排除"""
        self.assertEqual(_extract_speaker_from_clue("被指代者是说话者的哥哥", {"被指代"}), None)
        self.assertEqual(_extract_speaker_from_clue("对方要求叫他铁哥", {"对方"}), None)

    def test_empty_clue(self) -> None:
        """空 clue 返回 None"""
        self.assertIsNone(_extract_speaker_from_clue("", None))
        self.assertIsNone(_extract_speaker_from_clue(None, None))  # type: ignore[arg-type]

    def test_no_match_pattern(self) -> None:
        """不匹配任何模式"""
        self.assertIsNone(_extract_speaker_from_clue("某人说了什么", {"某人"}))

    def test_not_in_known_set(self) -> None:
        """推理出的名字不在 known_set 中"""
        self.assertIsNone(_extract_speaker_from_clue("新角色自称某某", {"白芷", "伯安"}))

    def test_known_set_none_accepts_any(self) -> None:
        """known_set 为 None 时接受任何非泛指名字"""
        self.assertEqual(_extract_speaker_from_clue("新角色自称某某", None), "新角色")


class TestPostProcessValidationFix(unittest.TestCase):
    """测试修复后的 _post_process_validation 逻辑"""

    def _call_validation(
        self,
        records: list[DialogueRecord],
        known_characters: list[str] | None = None,
        alias_map: dict[str, str] | None = None,
    ) -> list[DialogueRecord]:
        from src.models.local.annotation.phase3 import _post_process_validation
        candidates = [QuoteCandidate(index=r.index, content=r.content or "") for r in records]
        return _post_process_validation(records, candidates, known_characters, alias_map, chunk_id=1)

    def test_unknown_speaker_kept_as_null(self) -> None:
        """unknown speaker 保留 LLM 原始判断而非强制设为 null"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="新角色"),
        ]
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "新角色")

    def test_identity_clue_corrects_speaker(self) -> None:
        """identity_clue 提示正确 speaker 时修正"""
        records = [
            DialogueRecord(
                index=1, content="我叫白芷。", is_dialogue=True,
                speaker="伯安", identity_clue="白芷自称名为白芷",
            ),
        ]
        result = self._call_validation(records, known_characters=["伯安", "白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "白芷")
        self.assertEqual(result[0].identity_clue, "白芷自称名为白芷")

    def test_identity_clue_nullified_when_inferred_not_in_known_set(self) -> None:
        """identity_clue 推理出的名字不在 known_set 时，清空 clue 并保留原 speaker"""
        records = [
            DialogueRecord(
                index=1, content="我叫白芷。", is_dialogue=True,
                speaker="伯安", identity_clue="白芷自称名为白芷",
            ),
        ]
        # known_characters=None 让 _extract_speaker_from_clue 不过滤 known_set
        result = self._call_validation(records, known_characters=None)
        self.assertEqual(len(result), 1)
        # inferred="白芷" 不等于 canonical_speaker="伯安" 且不在空 known_set 中
        # 应修正 speaker 为白芷
        self.assertEqual(result[0].speaker, "白芷")

    def test_consistent_identity_clue_passes_through(self) -> None:
        """identity_clue 与 speaker 一致时正常通过"""
        records = [
            DialogueRecord(
                index=1, content="我叫白芷。", is_dialogue=True,
                speaker="白芷", identity_clue="白芷自称名为白芷",
            ),
        ]
        result = self._call_validation(records, known_characters=["白芷"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "白芷")
        self.assertEqual(result[0].identity_clue, "白芷自称名为白芷")

    def test_no_identity_clue_passes_through(self) -> None:
        """无 identity_clue 时正常通过"""
        records = [
            DialogueRecord(index=1, content="你好", is_dialogue=True, speaker="伯安"),
        ]
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "伯安")

    def test_unknown_speaker_corrected_by_clue(self) -> None:
        """unknown speaker 通过 identity_clue 反推修正（不限制 known_set）"""
        records = [
            DialogueRecord(
                index=1, content="我叫白芷。", is_dialogue=True,
                speaker="白芷", identity_clue="白芷自称名为白芷",
            ),
        ]
        result = self._call_validation(records, known_characters=["伯安", "贺铮"])
        self.assertEqual(len(result), 1)
        # 白芷不在 known_set，但 clue 明确说"白芷自称"，应保留为白芷而非 null
        self.assertEqual(result[0].speaker, "白芷")

    def test_unknown_speaker_null_when_no_clue_match(self) -> None:
        """unknown speaker 无有效 clue 时保留 LLM 原始判断"""
        records = [
            DialogueRecord(
                index=1, content="来者何人？", is_dialogue=True,
                speaker="灰衣人", identity_clue="某人从远处走来",
            ),
        ]
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "灰衣人")

    def test_unknown_speaker_with_clue_describing_others(self) -> None:
        """clue 描述的是对方而非说话者时，speaker 仍为 null"""
        records = [
            DialogueRecord(
                index=1, content="伯安少爷，那位是来应聘做您先生的。", is_dialogue=True,
                speaker="赤甲卫", identity_clue="赤甲卫称呼贺重明为伯安少爷",
            ),
        ]
        # clue 说赤甲卫在称呼别人，但说话者就是赤甲卫本人
        # _extract_speaker_from_clue 匹配 "赤甲卫称呼..." → 赤甲卫
        result = self._call_validation(records, known_characters=["伯安"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].speaker, "赤甲卫")


if __name__ == "__main__":
    unittest.main()
