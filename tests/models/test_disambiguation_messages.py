from __future__ import annotations

from src.models.local.disambiguation.messages import (
    _extract_evidence_types_from_context,
    build_anonymous_disambig_messages,
)


def test_extract_evidence_types_keeps_original_sentence_for_mixed_summary_context() -> None:
    context = "【前文总结】伯安曾在贺家露面\n伯安抬眼看向门外来人 | 【自报身份】他说自己姓贺"

    evidence_types = _extract_evidence_types_from_context(context)

    assert evidence_types == ["前文摘要-弱证据", "身份线索", "原文例句"]


def test_extract_evidence_types_does_not_add_original_sentence_for_summary_only_context() -> None:
    context = "【前文总结】伯安与贺家关系密切 | 【身份提示】旁人提到他与贺家有关"

    evidence_types = _extract_evidence_types_from_context(context)

    assert evidence_types == ["前文摘要-弱证据", "身份线索"]


def test_extract_evidence_types_does_not_treat_multiple_summaries_as_original_sentences() -> None:
    context = "【前文总结】伯安曾在贺家露面 | 他似乎与贺重明有旧"

    evidence_types = _extract_evidence_types_from_context(context)

    assert evidence_types == ["前文摘要-弱证据"]


def test_extract_evidence_types_keeps_original_sentence_after_multiple_summaries() -> None:
    context = "【前文总结】伯安曾在贺家露面 | 他似乎与贺重明有旧\n伯安抬眼看向门外来人"

    evidence_types = _extract_evidence_types_from_context(context)

    assert evidence_types == ["前文摘要-弱证据", "原文例句"]


def test_build_anonymous_disambig_messages_uses_common_name_label() -> None:
    messages = build_anonymous_disambig_messages(
        anonymous_names=["匿名_C1_0"],
        anonymous_contexts={"匿名_C1_0": "上下文"},
        existing_names=["伯安", "周凤兰"],
    )

    assert len(messages) == 2
    assert "【已知常用名】" in messages[1]["content"]
    assert "伯安" in messages[1]["content"]
    assert "周凤兰" in messages[1]["content"]
