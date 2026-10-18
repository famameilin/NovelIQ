"""现行章节标注的幂等身份与原文哈希合同"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from src.agents.annotation.ledger import AnnotationToolLedger
from src.fact_graph.graph import FactGraph
from src.fact_graph.inputs import ChapterParagraphInfo
from src.utils.identity import text_digest
from tests.support.annotation_work_tools import build_annotation_tools


def _tools(chapter_id: int, *, run_scope: str = "run-1") -> tuple[AnnotationToolLedger, dict[str, Any]]:
    content = "甲出发。"
    ledger = AnnotationToolLedger(
        run_scope=run_scope,
        current_chapter_id=chapter_id,
        current_chapter_text=content,
        allow_future_context=True,
        graph=FactGraph(run_scope=f"{run_scope}:{chapter_id}"),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[chapter_id],
            char_spans=[(0, len(content))],
            texts=[content],
        ),
    )
    return ledger, {item.name: item for item in build_annotation_tools(MagicMock(), ledger)}


def test_fresh_event_drafts_allocate_distinct_uuid7_identities() -> None:
    ids: list[tuple[str, str]] = []
    for run_scope, chapter_id in (("run-1", 1), ("run-1", 1), ("run-1", 2), ("run-2", 1)):
        ledger, tools = _tools(chapter_id, run_scope=run_scope)
        receipt = json.loads(
            tools["write_event"].invoke(
                {
                    "el": "t1",
                    "evidence": 1,
                    "title": "甲出发",
                    "problem": "明确事件问题",
                    "summary": "甲出发",
                    "event_type": "行动",
                    "status": "ongoing",
                }
            )
        )
        assert receipt["status"] == "written"
        tree = next(iter(ledger.event_trees.values()))
        ids.append((tree["tree_id"], tree["root_node_id"]))
    from uuid import UUID

    assert len(set(ids)) == 4
    assert all(UUID(identifier).version == 7 for pair in ids for identifier in pair)


def test_original_text_and_formal_payload_hash_preserve_whitespace_and_unicode() -> None:
    assert text_digest("原文") != text_digest(" 原文")
    assert text_digest("é") != text_digest("e\u0301")
