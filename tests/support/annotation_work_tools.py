"""使用当前 work 业务工具的轻量单元测试装配"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from src.agents.annotation.agent import WorkExecution
from src.agents.annotation.agent_ir import AgentAnnotation
from src.agents.annotation.work_tools import build_work_tools
from src.case_pool import CasePool
from src.event_trees.trees import EventTrees
from src.work.annotation_work import WorkReceipt, annotation_work_id


def _work_tools_context(query_service: Any, ledger: Any) -> tuple[Any, Any, Any]:
    """用于按当前 work 协议装配 build_work_tools 所需的 agent/execution 上下文"""
    invocation = uuid4().hex
    work = WorkReceipt(
        annotation_work_id(ledger.run_scope, ledger.current_chapter_id, ledger.role), ledger.run_scope, "annotation",
        {"chapter_id": ledger.current_chapter_id, "role": ledger.role},
    )
    execution = WorkExecution(work, invocation, ledger, AgentAnnotation(role=ledger.role))
    cases = CasePool(ledger.run_scope)
    trees = EventTrees(ledger.run_scope)
    # 作者身份收敛为单字符串：真实执行号就是三域的贡献作者
    cases.begin(invocation)
    trees.begin(invocation)
    agent = SimpleNamespace(
        run_id=ledger.run_scope, case_pool=cases, event_trees=trees, fact_graph=ledger.graph
    )
    ledger.work_id, ledger.invocation_id = work.work_id, invocation
    ledger.finish_work = execution.validate
    return agent, execution, query_service


def build_program_annotation_tools(query_service: Any, ledger: Any) -> list[Any]:
    """生产程序面使用 agent.py 同款 work 工具表，覆盖声明发布及局部键解析"""
    agent, execution, query = _work_tools_context(query_service, ledger)
    return build_work_tools(agent, execution, query)


def build_annotation_tools(query_service: Any, ledger: Any) -> list[Any]:
    """纯工具测试使用真实 work 协议，数据库事务由工作流集成测试覆盖"""
    agent, execution, query = _work_tools_context(query_service, ledger)
    # 领域单元测试隔离全书树发布；真实 work 发布和保存由工作流测试覆盖
    from src.agents.annotation.tool_factories import build_annotation_tools as build_domain_tools

    domain_tools = {tool.name: tool for tool in build_domain_tools(query_service, ledger)}
    return [
        domain_tools["write_event"] if tool.name == "write_event" else tool
        for tool in build_work_tools(agent, execution, query)
    ]


def build_program_test_runtime(tools: list[Any], ledger: Any, **kwargs: Any) -> Any:
    """单条领域工具测试复用现行程序解释器；模型可见面由集成测试检查"""
    from src.agents.annotation.agent_runtime import AgentProgramRuntime

    agent = ledger.finish_work.__self__.agent
    runtime = AgentProgramRuntime({tool.name: tool for tool in tools}, ledger, agent, **kwargs)
    runtime.tools.update(runtime.execution_tools)
    return runtime
