"""诊断 finish 合同与局部修正测试"""

import pytest

from src.storage.diagnosis_payload import AgentAnalysisPatch


def test_patch_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"unknown_field": 1})


def test_narrative_arc_type_caps_at_four_chars() -> None:
    """2026-09-25 叙事弧类型限 4 字短标签

    run faff5efe 诊断 LLM 曾把该自由字段写成 35 字箭头句（"少年成长弧：家族庇护→…"），
    仪表盘徽章被撑爆；finish 与 revise_finish 两条提交路径同受 4 字上限约束。
    """
    from src.agents.diagnosis.schema import AgentAnalysis

    accepted = AgentAnalysis.model_validate({"narrative_arc_type": "英雄之旅"})
    assert accepted.narrative_arc_type == "英雄之旅"
    with pytest.raises(ValueError):
        AgentAnalysis.model_validate({"narrative_arc_type": "少年成长弧：家族庇护→师承启蒙"})
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"narrative_arc_type": "少年成长弧：家族庇护"})
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"narrative_arc_type": ""})
