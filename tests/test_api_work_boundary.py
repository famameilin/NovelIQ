"""分层调用方向锁定

约定：
- api 是传输层，机制与领域包（agents/workflows/work/storage 等）不得反向依赖 src.api；
- api 只操作 workflows：任务/运行的读写与编排由 workflows 出面，api 不直接 import
  work 队列（api → workflows → work 队列/embedding/ltp/topic）；领域契约（诊断 payload、
  受控标签词表、情绪分值解析）落在 storage/config/metrics，api 与 agent 各自取用，
  api 不 import agents；
- agents 只被 workflows 调用：标注域契约（身份、实体/关系/对话/指标值域、提交与绑定
  模型、证据格式、作业身份）在 fact_graph，事件值域与事件绑定模型 + 程序面护栏在
  event_trees，被调用的三者不得反向依赖 src.agents；agents 也不得反向依赖 workflows；
- 事件侧单向：event_trees 取用事实图的共享件，事实图不反向依赖 event_trees；
- 编排层只派发：workflows 不 import fact_graph / event_trees / case_pool——三者的引擎由
  agent 自建，作业单元契约在 work，图谱就绪失败类型在 utils；
- 共用模块只有四个（config / utils / lexicons / event_bus）：它们位于依赖最底层，谁都可以依赖，
  但它们自己只允许在这四个之内互相引用，不得 import 任何领域或机制模块；
- work 是队列机制层，由 workflows 驱动，队列不得反向依赖 src.workflows。
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_API_ROOT = _SRC / "api"
_WORK_ROOT = _SRC / "work"
_AGENTS_ROOT = _SRC / "agents"
_WORKFLOWS_ROOT = _SRC / "workflows"
_FACT_GRAPH_ROOT = _SRC / "fact_graph"
_SHARED_MODULES = ("config", "utils", "lexicons", "event_bus")
_EVENT_TREES_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.event_trees(?:\.|$|\s)")
_GRAPH_DOMAIN_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.(?:fact_graph|event_trees|case_pool)(?:\.|$|\s)")
_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.api(?:\.|$|\s)")
_WORKFLOW_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.workflows(?:\.|$|\s)")
_QUEUE_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.work(?:\.|$|\s)")
_AGENTS_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.agents(?:\.|$|\s)")
_SRC_IMPORT_LINE = re.compile(r"^\s*(?:from|import)\s+src\.([A-Za-z_][A-Za-z0-9_]*)(?:\.|$|\s)")


def _offenders(root: Path, pattern: re.Pattern[str]) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.match(line):
                found.append(f"{path.relative_to(_SRC)}:{line_number}: {line.strip()}")
    return found


def test_only_api_depends_on_api() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.is_relative_to(_API_ROOT):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _IMPORT_LINE.match(line):
                offenders.append(f"{path.relative_to(_SRC)}:{line_number}: {line.strip()}")
    assert offenders == []


def test_api_does_not_depend_on_queue() -> None:
    assert _offenders(_API_ROOT, _QUEUE_IMPORT_LINE) == []


def test_api_does_not_depend_on_agents() -> None:
    assert _offenders(_API_ROOT, _AGENTS_IMPORT_LINE) == []


def test_queue_does_not_depend_on_workflows() -> None:
    assert _offenders(_WORK_ROOT, _WORKFLOW_IMPORT_LINE) == []


def test_only_workflows_depends_on_agents() -> None:
    """agents 是编排层独占的调用面；契约与护栏必须落在被调用侧"""
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.is_relative_to(_AGENTS_ROOT) or path.is_relative_to(_WORKFLOWS_ROOT):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _AGENTS_IMPORT_LINE.match(line):
                offenders.append(f"{path.relative_to(_SRC)}:{line_number}: {line.strip()}")
    assert offenders == []


def test_agents_does_not_depend_on_workflows() -> None:
    assert _offenders(_AGENTS_ROOT, _WORKFLOW_IMPORT_LINE) == []


def test_fact_graph_does_not_depend_on_event_trees() -> None:
    """事件侧单向：event_trees 取用事实图共享件，事实图不反向依赖事件树"""
    assert _offenders(_FACT_GRAPH_ROOT, _EVENT_TREES_IMPORT_LINE) == []


def test_shared_modules_depend_on_nothing_but_each_other() -> None:
    """共用模块只有 config / utils / lexicons / event_bus：位于最底层，不得依赖任何领域模块"""
    offenders: list[str] = []
    for name in _SHARED_MODULES:
        for path in sorted((_SRC / name).rglob("*.py")):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                match = _SRC_IMPORT_LINE.match(line)
                if match and match.group(1) not in _SHARED_MODULES:
                    offenders.append(f"{path.relative_to(_SRC)}:{line_number}: {line.strip()}")
    assert offenders == []


def test_storage_does_not_depend_on_event_trees() -> None:
    """章标注 payload 由标注 agent 校验，storage 只按行形态取值，不依赖事件树模型"""
    assert _offenders(_SRC / "storage", _EVENT_TREES_IMPORT_LINE) == []


def test_workflows_reaches_graph_domains_only_through_agents() -> None:
    """编排层只派发 work：事实图、事件树、案例池由 agent 自建并使用，workflows 不直接取用"""
    assert _offenders(_WORKFLOWS_ROOT, _GRAPH_DOMAIN_IMPORT_LINE) == []


def test_graph_domains_are_agent_only() -> None:
    """事实图、事件树、案例池是标注 agent 的私有域：除 agents 与这三者自身，谁都不 import"""
    domain_roots = tuple(_SRC / name for name in ("fact_graph", "event_trees", "case_pool"))
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.is_relative_to(_AGENTS_ROOT) or any(path.is_relative_to(root) for root in domain_roots):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _GRAPH_DOMAIN_IMPORT_LINE.match(line):
                offenders.append(f"{path.relative_to(_SRC)}:{line_number}: {line.strip()}")
    assert offenders == []
