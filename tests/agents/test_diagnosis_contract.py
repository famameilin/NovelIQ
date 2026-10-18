"""诊断 finish 合同与局部修正测试"""

import pytest

from src.diagnosis.patch import AgentAnalysisPatch


def test_patch_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"unknown_field": 1})


def test_narrative_arc_type_caps_at_four_chars() -> None:
    """叙事弧类型限 4 字短标签"""
    from src.diagnosis.schema import AgentAnalysis

    accepted = AgentAnalysis.model_validate({"narrative_arc_type": "英雄之旅"})
    assert accepted.narrative_arc_type == "英雄之旅"
    with pytest.raises(ValueError):
        AgentAnalysis.model_validate({"narrative_arc_type": "少年成长弧：家族庇护→师承启蒙"})
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"narrative_arc_type": "少年成长弧：家族庇护"})
    with pytest.raises(ValueError):
        AgentAnalysisPatch.model_validate({"narrative_arc_type": ""})
