"""
创建时间: 2026-04-26
修改者: Codex
任务: fix-phase2-setup-pool-followup-findings
说明: 覆盖 diagnosis 工作流日志的伏笔指标来源标签，避免与 setup-ledger expectation 混淆。
"""

from __future__ import annotations

from src.models.cloud.schema import CloudAnalysis
from src.workflows.diagnose import _log_diagnosis_results


def test_log_diagnosis_results_labels_llm_estimate(monkeypatch) -> None:
    """
    校验 diagnosis 工作流日志明确标注这是 LLM 估计值。

    创建时间: 2026-04-26
    修改者: Codex
    任务: fix-phase2-setup-pool-followup-findings
    新建原因: API 对外的 foreshadow_expectation 已改由 setup ledger 驱动，
    工作流日志不能再把 diagnosis 阶段的 foreshadow_rate 误标成同一个指标。
    """

    messages: list[str] = []

    def _capture(message: str) -> None:
        messages.append(message)

    monkeypatch.setattr("src.workflows.diagnose.logger.info", _capture)

    _log_diagnosis_results(
        CloudAnalysis(
            novel_id="novel-1",
            foreshadow_rate=0.35,
            arc_scores={"沈砚": 8.0},
            narrative_type="寓言",
            topic_labels=["成长"],
            diagnosis="ok",
            value_logic_type="善义有价值",
            narrative_arc_type="白手起家",
            protagonist="沈砚",
            main_characters=["沈砚"],
            core_cast=["沈砚"],
        )
    )

    assert any("Diagnosis LLM Foreshadow Estimate: 35.00%" in message for message in messages)
