"""保存线程的贡献不会被迟到调用或引用容器修改"""

import json
from dataclasses import FrozenInstanceError

import pytest

from src.case_pool.contributions import CaseContribution
from src.event_trees.contributions import EventContribution
from src.fact_graph.contributions import FactContribution
from src.fact_graph.evidence import EvidenceParagraph


def test_saved_contributions_isolate_nested_input_and_readers():
    original = {"nested": [{"value": "原值"}]}
    encoded = json.dumps(original)
    paragraph = EvidenceParagraph(1, 3, " 原文 ", 0, 4)
    values = [
        FactContribution("run", "work", "inv", 1, (paragraph,), encoded, "[]"),
        EventContribution("run", "work", "inv", 1, (paragraph,), encoded, "{}"),
        CaseContribution("run", "work", "inv", encoded),
    ]
    original["nested"][0]["value"] = "迟到写入"
    for value in values:
        read = value.snapshot()
        read["nested"][0]["value"] = "读方修改"
        assert value.snapshot()["nested"][0]["value"] == "原值"
        with pytest.raises(FrozenInstanceError):
            value.work_id = "其他执行"
    assert paragraph.text == " 原文 "
