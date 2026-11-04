"""结果存储形状与发布行为的无数据库契约"""

from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from src.storage.constraints import domain_constraint_statements
from src.storage.models import NarrativeGroup, NarrativeLink
from src.storage.records.models import NarrativeGroupRecord, NarrativeLinkRecord
from src.storage.repositories import organization_writes


def test_outcome_groups_and_event_links_have_no_independent_arc_shape():
    groups = NarrativeGroup.__table__
    links = NarrativeLink.__table__
    assert set(groups.c.keys()) == {
        "group_id",
        "producer_agent_id",
        "kind",
        "title",
        "description",
        "is_event_line",
        "line_name",
        "tree_key",
    }
    assert groups.c.description.nullable is False
    assert {item.name for item in fields(NarrativeGroupRecord)} == set(groups.c.keys())
    assert {item.name for item in fields(NarrativeLinkRecord)} == set(links.c.keys())
    assert not {"arc_group_id", "arc_role"} & set(links.c.keys())
    ddl = str(CreateTable(links).compile(dialect=postgresql.dialect()))
    assert "outcome_group_id" not in ddl
    assert "FOREIGN KEY(parent_tree_id) REFERENCES event_groups (group_id)" in ddl
    assert "FOREIGN KEY(semantic_source_event_id) REFERENCES event_records (event_id)" in ddl
    assert "arc_group_id" not in ddl
    assert {index.name for index in links.indexes} >= {
        "uq_tree_reference",
        "uq_event_member",
        "uq_narrative_links_operation",
    }
    statements = "\n".join(domain_constraint_statements())
    assert "dc_narrative_group_parent_chain" not in statements
    assert "parent_arc_id" not in statements
    assert "arc_group_id" not in statements
    assert "NEW.outcome_group_id" not in statements
    assert "dc_narrative_link_no_containment_cycle" in statements


def test_publication_only_writes_independent_outcomes_and_evidence():
    evidence = [SimpleNamespace(paragraph_id=1)]
    outcome = SimpleNamespace(
        outcome_id="outcome",
        producer_agent_id="report-agent",
        title="脱离险境",
        description="众人脱险",
        evidence=evidence,
    )
    organization = SimpleNamespace(source_agent_id="report-agent", outcomes=[outcome])
    session = Mock()
    with (
        patch.object(
            organization_writes._org_queries, "get_report", return_value=SimpleNamespace(agent_id="report-agent")
        ),
        patch.object(organization_writes._org_queries, "get_report_owner", return_value=SimpleNamespace(run_id="run")),
        patch.object(organization_writes._org_queries, "list_published_group_ids", return_value=[]),
        patch.object(organization_writes, "_write_evidence_rows") as write_evidence,
    ):
        organization_writes.save_organization(session, "run", organization, "report")
    published = [call.args[0] for call in session.add.call_args_list]
    assert len(published) == 1
    group = published[0]
    assert isinstance(group, NarrativeGroup)
    assert group.group_id == "outcome" and group.description == "众人脱险"
    assert group.kind == "outcome" and group.is_event_line is False
    assert group.producer_agent_id == "report-agent"
    assert write_evidence.call_args_list[0].args == (session, {"narrative_group_id": "outcome"}, evidence)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_existing_outcomes_are_not_replaced_during_publication():
    session = Mock()
    organization = SimpleNamespace(source_agent_id="report-agent", outcomes=[])
    with (
        patch.object(
            organization_writes._org_queries, "get_report", return_value=SimpleNamespace(agent_id="report-agent")
        ),
        patch.object(organization_writes._org_queries, "get_report_owner", return_value=SimpleNamespace(run_id="run")),
        patch.object(organization_writes._org_queries, "list_published_group_ids", return_value=["saved-outcome"]),
        pytest.raises(ValueError, match="已发布"),
    ):
        organization_writes.save_organization(session, "run", organization, "report")
    session.add.assert_not_called()
    session.flush.assert_not_called()
