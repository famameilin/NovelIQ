"""
创建时间: 2026-04-26
修改者: Codex
任务: fix-phase2-setup-pool-followup-findings
说明: 覆盖 diagnosis 工作流日志的正式预期输出标签。
"""

from __future__ import annotations

from src.models.cloud.schema import CloudAnalysis
from src.workflows.diagnose import _log_diagnosis_results


def test_log_diagnosis_results_labels_expectation(monkeypatch) -> None:
    """
    校验 diagnosis 工作流日志输出正式的伏笔回收预期字段。

    创建时间: 2026-04-26
    修改者: Codex
    任务: remove-foreshadow-rate-contract
    新建原因: 彻底移除 foreshadow_rate 后，工作流日志也必须只展示正式的 foreshadow_expectation。
    """

    messages: list[str] = []

    def _capture(message: str) -> None:
        messages.append(message)

    monkeypatch.setattr("src.workflows.diagnose.logger.info", _capture)

    _log_diagnosis_results(
        CloudAnalysis(
            novel_id="novel-1",
            foreshadow_expectation=0.35,
            arc_scores={"沈砚": 8.0},
            genre_labels=["通用"],
            style_labels=["严肃"],
            topic_labels=["成长"],
            diagnosis="ok",
            value_logic_type="善义有价值",
            narrative_arc_type="白手起家",
            focus_structure="single",
            focus_characters=["沈砚"],
            main_characters=["沈砚"],
            core_cast=["沈砚"],
        )
    )

    assert any("Foreshadow Expectation: 35.00%" in message for message in messages)
