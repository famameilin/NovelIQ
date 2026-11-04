"""全书结果的工具输入和正式草稿共用文字长度约束"""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import TypeAdapter, ValidationError

from src.agents.diagnosis.inputs import OutcomeItem
from src.agents.diagnosis.prompts import build_diagnosis_system_prompt
from src.agents.diagnosis.tools import build_diagnosis_tools
from src.event_trees.organization import EventOrganizationDraft
from src.event_trees.organization_models import (
    EventOutcomeDraft,
    NarrativeDescription,
    NarrativeTitle,
    OrganizationEvidence,
)
from tests.agents.test_diagnosis_organization import OrganizationCase
from tests.support.event_tree_fixtures import report_case_anchor
from tests.support.storage_fixtures import fixture_id, storage_for


@pytest.mark.parametrize("text_type,limit", [(NarrativeTitle, 6), (NarrativeDescription, 20)])
def test_limits_exclude_unicode_punctuation_and_preserve_original_text(text_type, limit):
    adapter = TypeAdapter(text_type)
    text = "甲" * limit + "，。！？：；、（）【】‘’“”…—.,!?;:()[]'\"-"
    assert adapter.validate_python(text) == text
    with pytest.raises(ValidationError, match=f"最多{limit}字.*重写"):
        adapter.validate_python("甲" * (limit + 1))


@pytest.mark.parametrize("text_type,limit", [(NarrativeTitle, 6), (NarrativeDescription, 20)])
@pytest.mark.parametrize("extra", ["+", "😀", " ", "a", "1"])
def test_symbols_spaces_letters_and_numbers_count_as_characters(text_type, limit, extra):
    with pytest.raises(ValidationError, match=f"最多{limit}字"):
        TypeAdapter(text_type).validate_python("甲" * limit + extra)


def test_tool_input_models_reject_over_limit_fields():
    payload = {
        "operation": "outcome",
        "key": "result",
        "title": "甲" * 6,
        "description": "乙" * 20,
        "evidence": [{"paragraph_id": 0}],
    }
    assert OutcomeItem.model_validate(payload).title == payload["title"]
    for field, limit in (("title", 6), ("description", 20)):
        with pytest.raises(ValidationError, match=f"最多{limit}字.*重写"):
            OutcomeItem.model_validate({**payload, field: "甲" * (limit + 1)})


def test_formal_draft_models_reject_over_limit_fields():
    payload = {
        "outcome_id": "outcome",
        "first_text_position": 0,
        "title": "甲" * 6,
        "description": "乙" * 20,
        "evidence": [{"paragraph_id": 0, "chapter_id": 1, "char_start": 0, "char_end": 1, "text_hash": "hash"}],
    }
    assert EventOutcomeDraft.model_validate(payload).title == payload["title"]
    for field, limit in (("title", 6), ("description", 20)):
        with pytest.raises(ValidationError, match=f"最多{limit}字.*重写"):
            EventOutcomeDraft.model_validate({**payload, field: "甲" * (limit + 1)})


def test_real_tool_schema_and_prompt_expose_semantic_limits():
    tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(MagicMock()), fixture_id(__name__, "run"), role="report", case_pool=MagicMock()
        )
    }
    schema = tools["write_outcome"].args_schema.model_json_schema()
    properties = schema["$defs"]["OutcomeItem"]["properties"]
    assert "最多6字" in properties["title"]["description"]
    assert "最多20字" in properties["description"]["description"]
    for field in ("title", "description"):
        assert "不计算Unicode标点" in properties[field]["description"]
        assert "maxLength" not in properties[field]
    assert "超限精简后重写" in tools["write_outcome"].description
    prompt = build_diagnosis_system_prompt(role="report")
    assert "标题最多6字，说明最多20字，不计算Unicode标点" in prompt


@pytest.fixture
def text_limit_draft(db_session):
    case = OrganizationCase(db_session, chapters=1)
    draft = EventOrganizationDraft(storage_for(db_session), case.run_id, case.session_id)
    draft.fixture_session = db_session
    draft.case_id = report_case_anchor(case.run_id)
    draft.producer_agent_id = case.agent_id
    return draft


def test_rejected_registration_and_tool_call_preserve_valid_draft(text_limit_draft):
    draft = text_limit_draft
    payload = {"key": "stable", "title": "身份确认", "description": "找回身份，化解危机。"}
    draft.register_outcome(**payload, evidence=[OrganizationEvidence(paragraph_id=0)])
    before = {key: value.model_dump() for key, value in draft.outcomes.items()}
    tools = {
        item.name: item
        for item in build_diagnosis_tools(
            storage_for(draft.fixture_session),
            draft.run_id,
            role="report",
            organization_draft=draft,
            case_pool=MagicMock(),
        )
    }
    for field, limit in (("title", 6), ("description", 20)):
        invalid = {**payload, field: "甲" * (limit + 1)}
        with pytest.raises(ValidationError, match="重写"):
            draft.register_outcome(**invalid, evidence=[OrganizationEvidence(paragraph_id=0)])
        with pytest.raises(ValidationError, match="重写"):
            tools["write_outcome"].invoke(
                {"items": [{**invalid, "operation": "outcome", "evidence": [{"paragraph_id": 0}]}]}
            )
        assert {key: value.model_dump() for key, value in draft.outcomes.items()} == before
    accepted = json.loads(
        tools["write_outcome"].invoke(
            {"items": [{**payload, "operation": "outcome", "evidence": [{"paragraph_id": 0}]}]}
        )
    )
    assert accepted["status"] == "written"
