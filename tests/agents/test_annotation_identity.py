"""现行章节标注的幂等身份与原文哈希合同"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from src.agents.annotation.fact_graph import FactGraph
from src.agents.annotation.identity import exact_digest, text_digest
from src.agents.annotation.schema import ChapterParagraphInfo
from src.agents.annotation.tools import AnnotationToolLedger, build_annotation_tools


def _tools(chapter_id: int, *, run_scope: str = "run-1") -> tuple[AnnotationToolLedger, dict[str, Any]]:
    content = "甲出发。"
    ledger = AnnotationToolLedger(
        run_scope=run_scope,
        current_chapter_id=chapter_id,
        current_chapter_text=content,
        allow_future_context=True,
        graph=FactGraph(run_scope=f"{run_scope}:{chapter_id}"),
        paragraph_info=ChapterParagraphInfo(
            paragraph_ids=[chapter_id], char_spans=[(0, len(content))], texts=[content],
        ),
    )
    return ledger, {item.name: item for item in build_annotation_tools(MagicMock(), ledger)}


def test_event_ids_are_stable_for_same_chapter_and_distinct_for_other_chapters_and_runs() -> None:
    ids: list[tuple[str, str]] = []
    for run_scope, chapter_id in (("run-1", 1), ("run-1", 1), ("run-1", 2), ("run-2", 1)):
        ledger, tools = _tools(chapter_id, run_scope=run_scope)
        receipt = json.loads(tools["write_event"].invoke({
            "el": "t1", "isroot": True, "description": "甲出发", "evidence": 1,
        }))
        assert receipt["status"] == "written"
        tree = next(iter(ledger.event_trees.values()))
        ids.append((tree["tree_id"], tree["root_node_id"]))
    assert ids[0] == ids[1]
    assert len({ids[0], ids[2], ids[3]}) == 3


def test_repeated_case_seed_uses_one_stable_target() -> None:
    ledger, tools = _tools(1)
    args = {"description": "身份有疑点", "keys": ["甲"], "type": "身份疑点"}
    first = json.loads(tools["push_case"].invoke(args))
    second = json.loads(tools["push_case"].invoke(args))
    assert second == {"accepted": True, "case_id": first["case_id"], "duplicate": True}
    assert len(ledger.pushed_cases) == 1


def test_case_ids_are_distinct_for_other_chapters_and_runs() -> None:
    ids: set[str] = set()
    for run_scope, chapter_id in (("run-1", 1), ("run-1", 2), ("run-2", 1)):
        _, tools = _tools(chapter_id, run_scope=run_scope)
        receipt = json.loads(tools["push_case"].invoke({
            "description": "身份有疑点", "keys": ["甲"], "type": "身份疑点",
        }))
        ids.add(receipt["case_id"])
    assert len(ids) == 3


def test_original_text_and_formal_payload_hash_preserve_whitespace_and_unicode() -> None:
    assert text_digest("原文") != text_digest(" 原文")
    assert text_digest("é") != text_digest("e\u0301")
    assert exact_digest({"content": "原文"}) != exact_digest({"content": "原文 "})
    assert exact_digest({"a": 1, "b": 2}) == exact_digest({"b": 2, "a": 1})
