"""诊断 finish 合同与局部修正测试"""

import pytest

from src.agents.diagnosis.contract import CloudAnalysisPatch
from src.agents.diagnosis.prompts import SYSTEM_PROMPT


def test_system_prompt_contains_contract_rules() -> None:
    assert "style_labels" in SYSTEM_PROMPT and "3" in SYSTEM_PROMPT
    assert "main_characters" in SYSTEM_PROMPT and "5" in SYSTEM_PROMPT
    assert "arc_scores" in SYSTEM_PROMPT
    assert "focus_structure" in SYSTEM_PROMPT


def test_patch_merge_semantics() -> None:
    patch = CloudAnalysisPatch.model_validate(
        {"style_labels": ["硬核"], "main_characters": ["石轩"]}
    )
    dumped = patch.model_dump(exclude_unset=True)
    assert dumped == {"style_labels": ["硬核"], "main_characters": ["石轩"]}


def test_patch_rejects_extra_fields() -> None:
    with pytest.raises(ValueError):
        CloudAnalysisPatch.model_validate({"unknown_field": 1})
