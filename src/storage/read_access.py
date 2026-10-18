"固定数据投影的公开读取接口"

from __future__ import annotations

from typing import Any

from src.storage.input_boundary import plain_inputs
from src.storage.repositories.queries import agents_annotation_agent as _agents_annotation_agent
from src.storage.repositories.queries import (
    agents_annotation_chapter_consolidation as _agents_annotation_chapter_consolidation,
)
from src.storage.repositories.queries import agents_annotation_queries as _agents_annotation_queries
from src.storage.repositories.queries import agents_diagnosis_persistence as _agents_diagnosis_persistence
from src.storage.repositories.queries import api_dependencies as _api_dependencies
from src.storage.repositories.queries import api_main as _api_main
from src.storage.repositories.queries import api_routes_results_graph as _api_routes_results_graph
from src.storage.repositories.queries import audit_module as _audit_module
from src.storage.repositories.queries import audit_queries as _audit_queries
from src.storage.repositories.queries import case_pool_pool as _case_pool_pool
from src.storage.repositories.queries import diagnosis_completion as _diagnosis_completion
from src.storage.repositories.queries import diagnosis_read as _diagnosis_read
from src.storage.repositories.queries import event_trees_action_order as _event_trees_action_order
from src.storage.repositories.queries import event_trees_organization as _event_trees_organization
from src.storage.repositories.queries import event_trees_read_foreshadowing as _event_trees_read_foreshadowing
from src.storage.repositories.queries import event_trees_read_organization as _event_trees_read_organization
from src.storage.repositories.queries import event_trees_trees as _event_trees_trees
from src.storage.repositories.queries import fact_graph_graph as _fact_graph_graph
from src.storage.repositories.queries import fact_graph_read_source as _fact_graph_read_source
from src.storage.repositories.queries import final_agents_annotation_text_search as _final_agents_annotation_text_search
from src.storage.repositories.queries import final_diagnosis_completion as _final_diagnosis_completion
from src.storage.repositories.queries import final_diagnosis_read as _final_diagnosis_read
from src.storage.repositories.queries import final_metrics_queries_plotline as _final_metrics_queries_plotline
from src.storage.repositories.queries import linguistic_completion as _linguistic_completion
from src.storage.repositories.queries import linguistic_queries as _linguistic_queries
from src.storage.repositories.queries import metrics_queries_annotations as _metrics_queries_annotations
from src.storage.repositories.queries import metrics_queries_completion as _metrics_queries_completion
from src.storage.repositories.queries import metrics_queries_fetchers as _metrics_queries_fetchers
from src.storage.repositories.queries import metrics_queries_plotline as _metrics_queries_plotline
from src.storage.repositories.queries import sse_persistence as _sse_persistence
from src.storage.repositories.queries import topic_completion as _topic_completion
from src.storage.repositories.queries import work_queries as _work_queries
from src.storage.repositories.queries import workflows_annotate as _workflows_annotate
from src.storage.repositories.queries import workflows_preprocess as _workflows_preprocess


@plain_inputs
class ReadAccess:
    def __init__(self, runner):
        self._runner = runner

    def agents_annotation_agent_query_1(self, execution_invocation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_1(session, execution_invocation_id),
            read_only=True,
        )

    def agents_annotation_agent_query_2(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_2(session, annotation_id),
            read_only=True,
        )

    def agents_annotation_agent_query_3(self) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_3(session), read_only=True
        )

    def agents_annotation_agent_query_4(self, message_invocation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_4(session, message_invocation_id),
            read_only=True,
        )

    def agents_annotation_agent_query_5(self, participant_fact: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_5(session, participant_fact),
            read_only=True,
        )

    def agents_annotation_agent_query_6(self, participant: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_6(session, participant),
            read_only=True,
        )

    def agents_annotation_agent_query_7(self, participant: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_7(session, participant),
            read_only=True,
        )

    def agents_annotation_agent_query_8(self, actual_relation_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_8(session, actual_relation_ids),
            read_only=True,
        )

    def agents_annotation_agent_query_9(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_9(session, annotation_id),
            read_only=True,
        )

    def agents_annotation_agent_query_10(self, message_invocation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_10(session, message_invocation_id),
            read_only=True,
        )

    def agents_annotation_agent_query_11(self, identifier: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_11(session, identifier),
            read_only=True,
        )

    def agents_annotation_agent_query_12(self, message_invocation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_agent.agents_annotation_agent_query_12(session, message_invocation_id),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_eligible_chapters_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_eligible_chapters_1(
                    session, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_2(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_2(
                    session, chapter_id, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_3(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_3(
                    session, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_4(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_4(
                    session, chapter_id, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_5(self, valid_executions: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_5(
                    session, valid_executions
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_6(self, fact_chapter: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_6(
                    session, fact_chapter
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_7(self, records_by_record: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_7(
                    session, records_by_record
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_8(self, declaration_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_8(
                    session, declaration_ids
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_9(self, declaration_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_9(
                    session, declaration_ids
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_10(self, valid_executions: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_10(
                    session, valid_executions
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_11(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_11(
                    session, chapter_id, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_12(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_12(
                    session, run_id
                )
            ),
            read_only=True,
        )

    def agents_annotation_chapter_consolidation_consolidate_chapter_14(self, lookup_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: (
                _agents_annotation_chapter_consolidation.agents_annotation_chapter_consolidation_consolidate_chapter_14(
                    session, lookup_ids
                )
            ),
            read_only=True,
        )

    def agents_annotation_queries_init_1(self, current_chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_queries.agents_annotation_queries_init_1(
                session, current_chapter_id, run_id
            ),
            read_only=True,
        )

    def agents_annotation_queries_init_2(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_queries.agents_annotation_queries_init_2(session, run_id), read_only=True
        )

    def agents_annotation_queries_read_1(self, paragraph_id: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_annotation_queries.agents_annotation_queries_read_1(session, paragraph_id, value_1),
            read_only=True,
        )

    def agents_diagnosis_persistence_character_entity_ids_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_diagnosis_persistence.agents_diagnosis_persistence_character_entity_ids_1(
                session, run_id
            ),
            read_only=True,
        )

    def agents_diagnosis_persistence_published_report_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _agents_diagnosis_persistence.agents_diagnosis_persistence_published_report_1(
                session, run_id
            ),
            read_only=True,
        )

    def api_dependencies_require_run_for_novel_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _api_dependencies.api_dependencies_require_run_for_novel_1(session, run_id), read_only=True
        )

    def api_main_health_check_1(self) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(lambda session: _api_main.api_main_health_check_1(session), read_only=True)

    def api_routes_results_graph_get_event_source_chapter_1(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _api_routes_results_graph.api_routes_results_graph_get_event_source_chapter_1(
                session, chapter_id, run_id
            ),
            read_only=True,
        )

    def api_routes_results_graph_get_event_source_chapter_2(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _api_routes_results_graph.api_routes_results_graph_get_event_source_chapter_2(
                session, chapter_id, run_id
            ),
            read_only=True,
        )

    def audit_module_skip_replayed_1(self, message_message_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_module.audit_module_skip_replayed_1(session, message_message_id), read_only=True
        )

    def audit_module_skip_replayed_2(self, message_message_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_module.audit_module_skip_replayed_2(session, message_message_id), read_only=True
        )

    def audit_queries_fetch_token_usage_stats_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_token_usage_stats_1(session, run_id), read_only=True
        )

    def audit_queries_detect_token_coverage_gaps_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_detect_token_coverage_gaps_1(session, run_id), read_only=True
        )

    def audit_queries_fetch_agent_turns_1(self, execution_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_agent_turns_1(session, execution_ids), read_only=True
        )

    def audit_queries_fetch_agent_turns_2(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_agent_turns_2(session, run_id), read_only=True
        )

    def audit_queries_fetch_run_tool_calls_1(self, call_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_run_tool_calls_1(session, call_ids), read_only=True
        )

    def audit_queries_fetch_usage_summary(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_usage_summary(session, run_id), read_only=True
        )

    def audit_queries_fetch_usage_by_task(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_usage_by_task(session, run_id), read_only=True
        )

    def audit_queries_fetch_usage_by_call_type(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_usage_by_call_type(session, run_id), read_only=True
        )

    def audit_queries_fetch_usage_by_model(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _audit_queries.audit_queries_fetch_usage_by_model(session, run_id), read_only=True
        )

    def case_pool_pool_observation_for_1(self, case: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_observation_for_1(session, case), read_only=True
        )

    def case_pool_pool_candidate_key_for_1(self, case: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_candidate_key_for_1(session, case, value_1), read_only=True
        )

    def case_pool_pool_delivery_dict_1(self, delivery: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_delivery_dict_1(session, delivery), read_only=True
        )

    def case_pool_pool_row_record_1(self, case: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_row_record_1(session, case), read_only=True
        )

    def case_pool_pool_load_cases_1(self, cases: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_cases_1(session, cases), read_only=True
        )

    def case_pool_pool_load_cases_2(self, cases: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_cases_2(session, cases), read_only=True
        )

    def case_pool_pool_load_cases_5(self, support: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_cases_5(session, support), read_only=True
        )

    def case_pool_pool_load_saved_work_1(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_saved_work_1(session, annotation_id), read_only=True
        )

    def case_pool_pool_load_saved_work_2(self, execution_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_saved_work_2(session, execution_id), read_only=True
        )

    def case_pool_pool_load_saved_work_3(self, support: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_saved_work_3(session, support), read_only=True
        )

    def case_pool_pool_load_saved_work_4(self, support: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _case_pool_pool.case_pool_pool_load_saved_work_4(session, support), read_only=True
        )

    def diagnosis_completion_has_diagnosis_data_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_completion.diagnosis_completion_has_diagnosis_data_1(session, run_id),
            read_only=True,
        )

    def diagnosis_completion_has_cast_1(self, cast_role: Any, report: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_completion.diagnosis_completion_has_cast_1(session, cast_role, report),
            read_only=True,
        )

    def diagnosis_completion_has_label_1(self, column: Any, report: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_completion.diagnosis_completion_has_label_1(session, column, report),
            read_only=True,
        )

    def diagnosis_read_fetch_diagnosis_payload_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_fetch_diagnosis_payload_1(session, run_id), read_only=True
        )

    def diagnosis_read_fetch_diagnosis_payload_2(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_fetch_diagnosis_payload_2(session, run_id), read_only=True
        )

    def diagnosis_read_fetch_diagnosis_payload_3(self, report_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_fetch_diagnosis_payload_3(session, report_id), read_only=True
        )

    def diagnosis_read_fetch_diagnosis_payload_4(self, report_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_fetch_diagnosis_payload_4(session, report_id), read_only=True
        )

    def diagnosis_read_labels_1(self, column: Any, report_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_labels_1(session, column, report_id), read_only=True
        )

    def diagnosis_read_members_1(self, cast_role: Any, report_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _diagnosis_read.diagnosis_read_members_1(session, cast_role, report_id), read_only=True
        )

    def event_trees_action_order_load_foreshadowing_actions_1(self, declarations: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_action_order.event_trees_action_order_load_foreshadowing_actions_1(
                session, declarations
            ),
            read_only=True,
        )

    def event_trees_action_order_load_foreshadowing_actions_2(self, declarations: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_action_order.event_trees_action_order_load_foreshadowing_actions_2(
                session, declarations, run_id
            ),
            read_only=True,
        )

    def event_trees_organization_published_arc_ids_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_published_arc_ids_1(session, run_id),
            read_only=True,
        )

    def event_trees_organization_run_annotation_records_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_run_annotation_records_1(
                session, run_id
            ),
            read_only=True,
        )

    def event_trees_organization_run_foreshadowing_actions_1(self, declarations: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_run_foreshadowing_actions_1(
                session, declarations
            ),
            read_only=True,
        )

    def event_trees_organization_run_conflict_rows_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_run_conflict_rows_1(session, run_id),
            read_only=True,
        )

    def event_trees_organization_parents_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_parents_1(session, value_1),
            read_only=True,
        )

    def event_trees_organization_declaration_rows_1(self, declaration_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_declaration_rows_1(
                session, declaration_ids
            ),
            read_only=True,
        )

    def event_trees_organization_declaration_rows_2(self, declaration_ids: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_declaration_rows_2(
                session, declaration_ids, value_1
            ),
            read_only=True,
        )

    def event_trees_organization_declaration_rows_3(self, records: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_declaration_rows_3(session, records),
            read_only=True,
        )

    def event_trees_organization_declaration_rows_4(self, participant_rows: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_declaration_rows_4(
                session, participant_rows
            ),
            read_only=True,
        )

    def event_trees_organization_read_passages_1(self, paragraph_ids: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_read_passages_1(
                session, paragraph_ids, value_1
            ),
            read_only=True,
        )

    def event_trees_organization_validate_subject_1(self, fact_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_organization.event_trees_organization_validate_subject_1(session, fact_id),
            read_only=True,
        )

    def event_trees_read_foreshadowing_foreshadowing_roots_1(self, declarations: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_foreshadowing.event_trees_read_foreshadowing_foreshadowing_roots_1(
                session, declarations
            ),
            read_only=True,
        )

    def event_trees_read_foreshadowing_bound_events_1(self, declaration_ids: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_foreshadowing.event_trees_read_foreshadowing_bound_events_1(
                session, declaration_ids, run_id
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_annotations_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_annotations_1(
                session, value_1
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_report_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_report_1(
                session, value_1
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_1(session, value_1),
            read_only=True,
        )

    def event_trees_read_organization_load_2(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_2(session, value_1),
            read_only=True,
        )

    def event_trees_read_organization_load_events_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_events_1(
                session, value_1
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_containments_1(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_containments_1(
                session, value_1
            ),
            read_only=True,
        )

    def event_trees_read_organization_declaration_participants_1(self, declaration_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_declaration_participants_1(
                session, declaration_ids
            ),
            read_only=True,
        )

    def event_trees_read_organization_declaration_participants_2(self, rows: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_declaration_participants_2(
                session, rows
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_declarations_1(self, records: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_declarations_1(
                session, records
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_revisions_1(self, event_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_revisions_1(
                session, event_ids
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_organization_1(self, producer_executions: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_organization_1(
                session, producer_executions
            ),
            read_only=True,
        )

    def event_trees_read_organization_load_organization_2(self, producer_executions: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_read_organization.event_trees_read_organization_load_organization_2(
                session, producer_executions
            ),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_1(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_1(session, annotation_id),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_2(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_2(session, annotation_id),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_3(self, declaration_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_3(session, declaration_ids),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_4(self, execution_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_4(session, execution_id),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_5(self, execution_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_5(session, execution_id),
            read_only=True,
        )

    def event_trees_trees_load_saved_work_6(self, participant_rows: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _event_trees_trees.event_trees_trees_load_saved_work_6(session, participant_rows),
            read_only=True,
        )

    def fact_graph_graph_execution_entities_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_execution_entities_1(session, run_id), read_only=True
        )

    def fact_graph_graph_load_saved_work_1(self, annotation_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_saved_work_1(session, annotation_id), read_only=True
        )

    def fact_graph_graph_load_saved_work_2(self, execution_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_saved_work_2(session, execution_id), read_only=True
        )

    def fact_graph_graph_load_saved_work_3(self, execution_chapter_id: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_saved_work_3(
                session, execution_chapter_id, value_1
            ),
            read_only=True,
        )

    def fact_graph_graph_read_execution_facts_1(self, rows: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_read_execution_facts_1(session, rows), read_only=True
        )

    def fact_graph_graph_read_execution_facts_2(self, rows: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_read_execution_facts_2(session, rows), read_only=True
        )

    def fact_graph_graph_read_execution_facts_3(self, execution_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_read_execution_facts_3(session, execution_id),
            read_only=True,
        )

    def fact_graph_graph_read_execution_facts_4(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_read_execution_facts_4(session, value_1), read_only=True
        )

    def fact_graph_graph_read_execution_facts_5(self) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_read_execution_facts_5(session), read_only=True
        )

    def fact_graph_graph_load_registry_1(self, facts: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_registry_1(session, facts), read_only=True
        )

    def fact_graph_graph_load_registry_2(self, fact: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_registry_2(session, fact), read_only=True
        )

    def fact_graph_graph_load_registry_3(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_registry_3(session, value_1), read_only=True
        )

    def fact_graph_graph_load_registry_4(self, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_graph.fact_graph_graph_load_registry_4(session, value_1), read_only=True
        )

    def fact_graph_read_source_read_evidence_source_1(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_read_source.fact_graph_read_source_read_evidence_source_1(
                session, chapter_id, run_id
            ),
            read_only=True,
        )

    def fact_graph_read_source_read_evidence_source_2(self, chapter_id: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _fact_graph_read_source.fact_graph_read_source_read_evidence_source_2(
                session, chapter_id, run_id
            ),
            read_only=True,
        )

    def final_agents_annotation_text_search_search_1(
        self, after_chapter_sequence: Any, before_chapter_sequence: Any, merged: Any, value_1: Any
    ) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_agents_annotation_text_search.final_agents_annotation_text_search_search_1(
                session, after_chapter_sequence, before_chapter_sequence, merged, value_1
            ),
            read_only=True,
        )

    def final_diagnosis_completion_has_diagnosis_data_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_diagnosis_completion.final_diagnosis_completion_has_diagnosis_data_1(
                session, run_id
            ),
            read_only=True,
        )

    def final_diagnosis_read_declaration_bindings_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_diagnosis_read.final_diagnosis_read_declaration_bindings_1(session, run_id),
            read_only=True,
        )

    def final_metrics_queries_plotline_fetch_facts_1(self, chapter_ids: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_metrics_queries_plotline.final_metrics_queries_plotline_fetch_facts_1(
                session, chapter_ids, value_1
            ),
            read_only=True,
        )

    def final_metrics_queries_plotline_direct_facts(self, run_id: Any, chapter_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_metrics_queries_plotline.final_metrics_queries_plotline_direct_facts(
                session, run_id, chapter_ids
            ),
            read_only=True,
        )

    def final_metrics_queries_plotline_bindings(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _final_metrics_queries_plotline.final_metrics_queries_plotline_bindings(session, run_id),
            read_only=True,
        )

    def linguistic_completion_is_linguistic_complete_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _linguistic_completion.linguistic_completion_is_linguistic_complete_1(session, run_id),
            read_only=True,
        )

    def linguistic_queries_fetch_paragraph_labels_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _linguistic_queries.linguistic_queries_fetch_paragraph_labels_1(session, run_id),
            read_only=True,
        )

    def metrics_queries_annotations_fetch_paragraph_label_counts_1(self, record_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_annotations.metrics_queries_annotations_fetch_paragraph_label_counts_1(
                session, record_ids
            ),
            read_only=True,
        )

    def metrics_queries_completion_is_aggregate_complete_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_completion.metrics_queries_completion_is_aggregate_complete_1(
                session, run_id
            ),
            read_only=True,
        )

    def metrics_queries_completion_is_aggregate_complete_2(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_completion.metrics_queries_completion_is_aggregate_complete_2(
                session, run_id
            ),
            read_only=True,
        )

    def metrics_queries_fetchers_fetch_chapter_progress_map_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_fetchers.metrics_queries_fetchers_fetch_chapter_progress_map_1(
                session, run_id
            ),
            read_only=True,
        )

    def metrics_queries_fetchers_fetch_chapter_progress_map_2(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_fetchers.metrics_queries_fetchers_fetch_chapter_progress_map_2(
                session, run_id
            ),
            read_only=True,
        )

    def metrics_queries_fetchers_fetch_chapter_progress_map_3(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_fetchers.metrics_queries_fetchers_fetch_chapter_progress_map_3(
                session, run_id
            ),
            read_only=True,
        )

    def metrics_queries_plotline_init_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_plotline.metrics_queries_plotline_init_1(session, run_id), read_only=True
        )

    def metrics_queries_plotline_evidence_by_owner_1(self, owner_column: Any, owner_ids: Any, value_1: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_plotline.metrics_queries_plotline_evidence_by_owner_1(
                session, owner_column, owner_ids, value_1
            ),
            read_only=True,
        )

    def metrics_queries_plotline_fetch_fact_tags_1(self, fact_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _metrics_queries_plotline.metrics_queries_plotline_fetch_fact_tags_1(session, fact_ids),
            read_only=True,
        )

    def sse_persistence_display_state_1(self, _RESET_EVENT_TYPES: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _sse_persistence.sse_persistence_display_state_1(session, _RESET_EVENT_TYPES, run_id),
            read_only=True,
        )

    def topic_completion_is_topic_model_complete_1(self, model: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _topic_completion.topic_completion_is_topic_model_complete_1(session, model, run_id),
            read_only=True,
        )

    def work_queries_paragraph_labels_1(self, record_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_paragraph_labels_1(session, record_ids), read_only=True
        )

    def work_queries_declaration_projections_1(self, declarations: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_declaration_projections_1(session, declarations), read_only=True
        )

    def work_queries_declaration_projections_2(self, record_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_declaration_projections_2(session, record_ids), read_only=True
        )

    def work_queries_dialogue_projections_1(self, execution_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_dialogue_projections_1(session, execution_ids), read_only=True
        )

    def work_queries_character_observations_1(self, record_by_declaration: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_character_observations_1(session, record_by_declaration),
            read_only=True,
        )

    def work_queries_character_observations_2(self, record_ids: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_character_observations_2(session, record_ids), read_only=True
        )

    def work_queries_paragraph_record(self, run_id: Any, paragraph_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _work_queries.work_queries_paragraph_record(session, run_id, paragraph_id), read_only=True
        )

    def workflows_annotate_load_work_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _workflows_annotate.workflows_annotate_load_work_1(session, run_id), read_only=True
        )

    def workflows_annotate_load_work_2(self, chapter: Any, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _workflows_annotate.workflows_annotate_load_work_2(session, chapter, run_id), read_only=True
        )

    def workflows_preprocess_generate_paragraph_embeddings_1(self, run_id: Any) -> Any:
        "读取固定数据投影，连接和结果资源在包内释放"
        return self._runner.run(
            lambda session: _workflows_preprocess.workflows_preprocess_generate_paragraph_embeddings_1(session, run_id),
            read_only=True,
        )
