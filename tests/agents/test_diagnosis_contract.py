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


def test_topic_labels_accept_integer_topic_ids() -> None:
    """read_topics 返回整数 topic_id，完整提交与局部修正都按同一口径收成字符串键"""
    from src.diagnosis.schema import AgentAnalysis

    analysis = AgentAnalysis.model_validate({"topic_labels": {0: "家事", 3: "少年"}})
    assert analysis.topic_labels == {"0": "家事", "3": "少年"}
    patch = AgentAnalysisPatch.model_validate({"topic_labels": {7: "朝局"}})
    assert patch.topic_labels == {"7": "朝局"}
    with pytest.raises(ValueError):
        AgentAnalysis.model_validate({"topic_labels": {"x": "家事"}})


def test_label_rejection_names_allowed_values() -> None:
    """标签拒收回执带完整可用值，无需再查提示词"""
    from src.diagnosis.schema import AgentAnalysis

    with pytest.raises(ValueError, match="可用值") as genre:
        AgentAnalysis.model_validate({"genre_labels": ["自创题材"]})
    assert "科幻" in str(genre.value)
    with pytest.raises(ValueError, match="可用值") as style:
        AgentAnalysis.model_validate({"style_labels": ["自创风格"]})
    assert "硬核" in str(style.value)
