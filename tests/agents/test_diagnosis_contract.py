"""诊断 finish 合同与局部修正测试"""

import pytest

from src.agents.diagnosis.contract import CloudAnalysisPatch


def test_patch_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        CloudAnalysisPatch.model_validate({"unknown_field": 1})
