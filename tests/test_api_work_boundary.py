"""用 AST 验证职责方向，ORM、SQL 和事务只能存在于 Storage 内部"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.support.module_dependencies import (
    api_write_violations,
    cycles,
    dependencies,
    metrics_calculation_violations,
    reexport_dependencies,
)

_ROOT = Path(__file__).resolve().parents[1]
_ALLOWED = {
    "api": {
        "audit",
        "config",
        "diagnosis",
        "event_trees",
        "fact_graph",
        "linguistic",
        "metrics",
        "sse",
        "storage",
        "topic",
        "workflows",
    },
    "workflows": {
        "agents",
        "audit",
        "config",
        "diagnosis",
        "embedding",
        "event_bus",
        "fact_graph",
        "lexicons",
        "linguistic",
        "metrics",
        "model_pool",
        "sse",
        "storage",
        "text_processing",
        "topic",
        "utils",
        "work",
    },
    "agents": {
        "audit",
        "case_pool",
        "config",
        "diagnosis",
        "embedding",
        "event_bus",
        "event_trees",
        "fact_graph",
        "model_pool",
        "sse",
        "storage",
        "utils",
        "work",
    },
    "work": {"config", "event_bus", "model_pool", "storage", "utils"},
    "model_pool": {"config", "embedding", "event_bus", "storage", "utils"},
    "embedding": {"config"},
    "audit": {"event_bus", "storage"},
    "diagnosis": {"config", "event_trees", "fact_graph", "metrics", "storage", "topic", "utils"},
    "text_processing": {"lexicons"},
    "fact_graph": {"storage", "utils"},
    "event_trees": {"fact_graph", "storage", "utils"},
    "case_pool": {"storage", "utils"},
    "metrics": {"config", "event_trees", "fact_graph", "lexicons", "storage", "text_processing", "utils", "work"},
    "linguistic": {"config", "lexicons", "metrics", "storage", "text_processing"},
    "topic": {"config", "lexicons", "storage"},
    "storage": {"config", "utils"},
    "sse": {"event_bus", "storage"},
    "lexicons": set(),
    "config": set(),
    "utils": set(),
    "event_bus": set(),
}


def _project_dependencies():
    return [d for d in dependencies(_ROOT) if d.target.startswith("src.")]


def test_modules_and_dependency_whitelist() -> None:
    modules = {p.name for p in (_ROOT / "src").iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    assert modules == set(_ALLOWED)
    violations = []
    for d in _project_dependencies():
        source, target = d.source.split(".")[1], d.target.split(".")[1]
        if source != target and target not in _ALLOWED[source]:
            violations.append(f"{d.source}:{d.line} -> {d.target}")
    assert not violations, "\n".join(violations)


def test_runtime_dependencies_have_no_cycles() -> None:
    imports = [d for d in _project_dependencies() + reexport_dependencies(_ROOT) if not d.type_only]
    # 文件级：真实执行链不得存在任何导入环
    assert cycles((d.source, d.target) for d in imports) == []
    # 领域投影在各自包中计算，存储不能反向导入领域形成强连通集合
    assert cycles((d.source.split(".")[1], d.target.split(".")[1]) for d in imports) == []



def test_http_framework_belongs_to_api() -> None:
    bad = [
        f"{d.source}:{d.line} -> {d.target}"
        for d in dependencies(_ROOT)
        if d.target.split(".")[0] in {"fastapi", "starlette", "sse_starlette"} and not d.source.startswith("src.api.")
    ]
    assert bad == []


def test_api_uses_read_interfaces_not_write_engines() -> None:
    assert api_write_violations(_ROOT) == []


def test_metrics_calculation_does_not_read_database_or_network() -> None:
    assert metrics_calculation_violations(_ROOT) == []


def test_api_guard_rejects_write_reexport(tmp_path: Path) -> None:
    for module, code in {
        "api/query": "from src.fact_graph.read.facade import save_work\n",
        "fact_graph/read/facade": "from ..graph import save_work\n",
        "fact_graph/graph": "def save_work(): pass\n",
    }.items():
        path = tmp_path / "src" / (module + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code)
    assert api_write_violations(tmp_path) == ["src.api.query:1 -> src.fact_graph.graph"]


def test_calculation_guard_rejects_query_and_transitive_database(tmp_path: Path) -> None:
    for module, code in {
        "metrics/calculate": "from .queries.helper import load\nfrom src.utils.helper import value\n",
        "metrics/queries/helper": "import sqlalchemy\n",
        "utils/helper": "def load():\n    import sqlalchemy\n",
    }.items():
        path = tmp_path / "src" / (module + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code)
    assert metrics_calculation_violations(tmp_path) == [
        "src.metrics.calculate -> src.metrics.queries.helper",
        "src.metrics.calculate -> src.utils.helper -> sqlalchemy",
    ]


def test_calculation_guard_allows_type_only_database_reference(tmp_path: Path) -> None:
    path = tmp_path / "src/metrics/calculate.py"
    path.parent.mkdir(parents=True)
    path.write_text("from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import sqlalchemy\n")
    assert metrics_calculation_violations(tmp_path) == []


def test_model_pool_does_not_consume_business_envelopes() -> None:
    for path in (_ROOT / "src/model_pool").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        assert not any(isinstance(n, ast.Name) and n.id == "WorkReceipt" for n in ast.walk(tree)), str(path)


def test_deprecated_is_unreferenced() -> None:
    """退役代码可以保留在仓库，正式执行链不得导入"""
    assert not any(d.target == "deprecated" or d.target.startswith("deprecated.") for d in dependencies(_ROOT))


def test_parser_covers_relative_nested_and_dynamic_imports(tmp_path: Path) -> None:
    package = tmp_path / "src/sample"
    package.mkdir(parents=True)
    (tmp_path / "src/__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "leaf.py").write_text("")
    (package / "consumer.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "from importlib import import_module as load\n"
        "from . import leaf\n"
        "if TYPE_CHECKING:\n    from src.sample.leaf import Kind\n"
        "def run():\n    from .leaf import value\n"
        '    load("src.sample.leaf")\n    load(f"{__package__}.leaf")\n'
    )
    imports = [d for d in dependencies(tmp_path) if d.source == "src.sample.consumer" and d.target == "src.sample.leaf"]
    assert len(imports) == 5
    assert sum(d.type_only for d in imports) == 1
    assert sum(d.dynamic for d in imports) == 2


def test_contracts_do_not_reexport_their_consumers() -> None:
    bad = [
        d
        for d in _project_dependencies()
        if d.source == "src.fact_graph.schema"
        and d.target.startswith(("src.fact_graph.inputs", "src.fact_graph.outputs"))
    ]
    assert not bad
    assert not any(
        d.source.startswith("src.storage.")
        and d.target.split(".")[1] not in {"storage"} | _ALLOWED["storage"]
        for d in reexport_dependencies(_ROOT)
    )


def test_reexport_parser_resolves_actual_definition(tmp_path: Path) -> None:
    package = tmp_path / "src/example"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .facade import Contract\n")
    (package / "leaf.py").write_text("class Contract: pass\n")
    (package / "facade.py").write_text("from .leaf import Contract\n")
    (package / "caller.py").write_text("def call():\n    from .facade import Contract\n")
    result = reexport_dependencies(tmp_path)
    assert any(d.source == "src.example.caller" and d.target == "src.example.leaf" for d in result)
    assert any(d.source == "src.example" and d.target == "src.example.leaf" for d in result)


def test_annotation_state_ownership_is_explicit() -> None:
    owner_fields = {
        "state_entities": {"written_entities", "written_relations", "entity_el_index"},
        "state_events": {"event_trees", "pending_child_events", "observation_by_record"},
        "state_dialogue": {"source_anchors", "written_dialogues", "authorized_text_paragraph_ids"},
        "state_metrics": {"metrics_payload", "bound_payloads"},
    }
    for module, expected in owner_fields.items():
        tree = ast.parse((_ROOT / f"src/agents/annotation/{module}.py").read_text(encoding="utf-8"))
        classes = [
            n
            for n in tree.body
            if isinstance(n, ast.ClassDef)
            and any(isinstance(d, ast.Call) and ast.unparse(d.func) == "dataclass" for d in n.decorator_list)
        ]
        fields = {
            n.target.id
            for cls in classes
            for n in cls.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        assert expected <= fields
        assert not any(isinstance(n, ast.FunctionDef) and n.name == "__getattr__" for n in ast.walk(tree))
    ledger = ast.parse((_ROOT / "src/agents/annotation/ledger.py").read_text(encoding="utf-8"))
    ledger_class = next(n for n in ledger.body if isinstance(n, ast.ClassDef) and n.name == "AnnotationToolLedger")
    fields = {n.target.id for n in ledger_class.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    assert {"entities", "events", "dialogue", "metrics"} <= fields
    assert not fields & set().union(*owner_fields.values())


def test_domain_save_consumes_frozen_contributions() -> None:
    for module, leaf, contribution in (
        ("fact_graph", "graph", "FactContribution"),
        ("event_trees", "trees", "EventContribution"),
        ("case_pool", "__init__", "CaseContribution"),
    ):
        tree = ast.parse((_ROOT / f"src/{module}/{leaf}.py").read_text(encoding="utf-8"))
        tree = ast.parse((_ROOT / f"src/{module}/contributions.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == contribution)
        assert any(
            isinstance(d, ast.Call)
            and any(
                k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True for k in d.keywords
            )
            for d in cls.decorator_list
        )


def test_stage_completion_rules_do_not_belong_to_storage() -> None:
    retired = {
        "is_preprocess_complete",
        "is_linguistic_complete",
        "is_topic_model_complete",
        "is_aggregate_complete",
        "has_diagnosis_data",
        "_payload_has_valid_diagnosis_contract",
    }
    for path in (_ROOT / "src/storage").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.FunctionDef) and n.name in retired for n in ast.walk(tree)), str(path)


def test_sse_display_rules_belong_to_sse() -> None:
    tree = ast.parse((_ROOT / "src/storage/repositories/event_outbox.py").read_text(encoding="utf-8"))
    assert not any(
        getattr(n, "name", None) in {"DisplayState", "display_scope", "replay", "_display_state", "display_state"}
        for n in ast.walk(tree)
    )


def test_config_does_not_export_domain_rules() -> None:
    prohibited = {
        "PROPP_FUNCTIONS",
        "SEMANTIC_CATEGORY_MAPPING",
        "LEXICON_FILES",
        "LEXICON_DRAFT_KEYS",
        "TITLE_ALIAS_SUFFIXES",
        "ALLOWED_PREV_CJK_CHARS",
        "LIKELY_NAME_PREFIX_CHARS",
    }
    for path in (_ROOT / "src/config").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.Name) and n.id in prohibited for n in ast.walk(tree)), str(path)


def test_only_storage_imports_orm_and_private_database_modules() -> None:
    violations = []
    private = ("src.storage.db", "src.storage.models", "src.storage.repositories", "src.storage.session", "src.storage.operations")
    for dependency in dependencies(_ROOT):
        if dependency.source.startswith("src.storage."):
            continue
        if dependency.target == "sqlalchemy" or dependency.target.startswith("sqlalchemy.") or any(dependency.target == prefix or dependency.target.startswith(prefix + ".") for prefix in private):
            violations.append(f"{dependency.source}:{dependency.line} -> {dependency.target}")
    assert violations == []
