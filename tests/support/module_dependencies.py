"""架构检查用 AST 依赖解析器，包含相对、函数内及可解析动态导入"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Dependency:
    source: str
    target: str
    line: int
    type_only: bool = False
    dynamic: bool = False


def module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def dependencies(root: Path) -> list[Dependency]:
    files = {module_name(p, root): p for p in (root / "src").rglob("*.py")}
    result: list[Dependency] = []
    for name, path in sorted(files.items()):
        result.extend(_dependencies_for(name, path, files))
    return sorted(set(result), key=lambda d: (d.source, d.line, d.target, d.type_only))


def _dependencies_for(name: str, path: Path, files: dict[str, Path]) -> list[Dependency]:
    result: list[Dependency] = []
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    constants: dict[str, str] = {"__package__": package, "__name__": name}
    dynamic_names = {"importlib.import_module", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            dynamic_names.update(a.asname or a.name for a in node.names if a.name == "import_module")
        if isinstance(node, ast.Import):
            dynamic_names.update(
                (a.asname or "importlib") + ".import_module" for a in node.names if a.name == "importlib"
            )

    def value(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = value(node.left), value(node.right)
            return left + right if left is not None and right is not None else None
        if isinstance(node, ast.JoinedStr):
            parts = [value(n.value) if isinstance(n, ast.FormattedValue) else value(n) for n in node.values]
            return (
                "".join(part for part in parts if part is not None) if all(part is not None for part in parts) else None
            )
        return None

    def resolve(target: str, level: int = 0) -> str:
        if level:
            parts = package.split(".")
            if level > len(parts):
                raise ValueError(f"{name}: 相对导入越界")
            return ".".join(parts[: len(parts) - level + 1] + ([target] if target else []))
        if target.startswith("."):
            depth = len(target) - len(target.lstrip("."))
            return resolve(target.lstrip("."), depth)
        return target

    def add(target: str, node: ast.AST, type_only: bool, dynamic: bool = False) -> None:
        if target.startswith("src.") or target in files or not target.startswith("."):
            result.append(Dependency(name, target, node.lineno, type_only, dynamic))

    def walk(node: ast.AST, type_only: bool = False) -> None:
        if isinstance(node, ast.If):
            test = ast.unparse(node.test)
            guarded = test in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}
            for child in node.body:
                walk(child, type_only or guarded)
            for child in node.orelse:
                walk(child, type_only)
            return
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            text = value(node.value)
            if text is not None:
                constants[node.targets[0].id] = text
        if isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, node, type_only)
        elif isinstance(node, ast.ImportFrom):
            target = resolve(node.module or "", node.level)
            for alias in node.names:
                child = target + "." + alias.name
                add(child if child in files else target, node, type_only)
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in dynamic_names and node.args:
            text = value(node.args[0])
            if text is not None:
                add(resolve(text), node, type_only, True)
        for child in ast.iter_child_nodes(node):
            walk(child, type_only)

    walk(tree)
    return result


def cycles(edges: Iterable[tuple[str, str]]) -> list[tuple[str, ...]]:
    """Tarjan 强连通分量，只返回包含实际依赖环的模块集合"""
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        if source != target:
            graph.setdefault(source, set()).add(target)
            graph.setdefault(target, set())
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    found: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in index:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], index[target])
        if low[node] == index[node]:
            component = []
            while True:
                item = stack.pop()
                active.remove(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                found.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in index:
            visit(node)
    return sorted(found)


def reexport_dependencies(root: Path) -> list[Dependency]:
    """解析 from-import 的导出链，补上消费者到实际定义模块的依赖"""
    files = {module_name(p, root): p for p in (root / "src").rglob("*.py")}
    bindings: dict[tuple[str, str], tuple[str, str]] = {}
    imports: list[tuple[str, str, str, int, bool]] = []
    for module, path in files.items():
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))

        def visit(
            nodes: list[ast.stmt],
            type_only: bool = False,
            public: bool = True,
            *,
            source: str = module,
            source_package: str = package,
        ) -> None:
            for node in nodes:
                if isinstance(node, ast.ImportFrom):
                    parts = source_package.split(".")
                    target = (
                        ".".join(parts[: len(parts) - node.level + 1] + ([node.module] if node.module else []))
                        if node.level
                        else node.module or ""
                    )
                    for alias in node.names:
                        if target + "." + alias.name in files:
                            continue
                        if target in files:
                            imports.append((source, target, alias.name, node.lineno, type_only))
                            if public:
                                bindings[source, alias.asname or alias.name] = (target, alias.name)
                elif isinstance(node, ast.If):
                    guarded = ast.unparse(node.test) in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}
                    visit(node.body, type_only or guarded, public)
                    visit(node.orelse, type_only, public)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    visit(node.body, type_only, False)

        visit(tree.body)

    def origin(module: str, symbol: str) -> str:
        seen: set[tuple[str, str]] = set()
        while (module, symbol) in bindings:
            if (module, symbol) in seen:
                raise ValueError(f"循环导出: {sorted(seen)}")
            seen.add((module, symbol))
            module, symbol = bindings[module, symbol]
        return module

    return [
        Dependency(source, origin(target, symbol), line, type_only)
        for source, target, symbol, line, type_only in imports
    ]
