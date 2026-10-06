"""使用当前 work 业务工具的轻量单元测试装配"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from src.agents.annotation.agent import WorkExecution
from src.agents.annotation.subagent_ir import SubagentAnnotation
from src.agents.annotation.work import WorkReceipt, annotation_work_id
from src.agents.annotation.work_tools import build_work_tools
from src.case_pool import CasePool
from src.event_trees.trees import EventTrees


def build_annotation_tools(query_service: Any, ledger: Any) -> list[Any]:
    """纯工具测试使用真实 work 协议，数据库事务由工作流集成测试覆盖"""
    invocation = uuid4().hex
    work = WorkReceipt(
        annotation_work_id(ledger.run_scope, ledger.current_chapter_id, ledger.role), ledger.run_scope, "annotation",
        {"chapter_id": ledger.current_chapter_id, "role": ledger.role},
    )
    execution = WorkExecution(work, invocation, ledger, SubagentAnnotation(role=ledger.role))
    cases = CasePool(ledger.run_scope)
    trees = EventTrees(ledger.run_scope)
    cases.begin(work.work_id, invocation)
    trees.begin(work.work_id, invocation)
    agent = SimpleNamespace(case_pool=cases, event_trees=trees, fact_graph=ledger.graph)
    ledger.work_id, ledger.invocation_id = work.work_id, invocation
    ledger.finish_work = execution.validate
    # 领域单元测试隔离全书树发布；真实 work 发布和保存由工作流测试覆盖
    from src.agents.annotation.tool_factories import build_annotation_tools as build_domain_tools

    domain_tools = {tool.name: tool for tool in build_domain_tools(query_service, ledger)}
    return [
        domain_tools["write_event"] if tool.name == "write_event" else tool
        for tool in build_work_tools(agent, execution, query_service)
    ]


def build_program_test_runtime(tools: list[Any], ledger: Any, **kwargs: Any) -> Any:
    """单条领域工具测试复用现行程序解释器；模型可见面由集成测试检查"""
    from src.agents.annotation.subagent_runtime import SubagentProgramRuntime

    subagent = ledger.finish_work.__self__.subagent
    runtime = SubagentProgramRuntime({tool.name: tool for tool in tools}, ledger, subagent, **kwargs)
    runtime.tools.update(runtime.execution_tools)
    return runtime
