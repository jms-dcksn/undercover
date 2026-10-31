"""Keep runtime composition above tools, storage and business operations."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def product_modules() -> dict[str, ast.Module]:
    paths = [ROOT / "telemetry.py"]
    paths.extend(
        path
        for package in ("agent", "backend")
        for path in (ROOT / package).glob("*.py")
    )
    return {
        ".".join(path.relative_to(ROOT).with_suffix("").parts): ast.parse(
            path.read_text()
        )
        for path in paths
    }


def imports(tree: ast.Module) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_dependencies_point_toward_shared_modules():
    for module, tree in product_modules().items():
        dependencies = imports(tree)
        assert "backend.main" not in dependencies, module
        if module == "telemetry":
            assert not any(
                name.startswith(("agent", "backend")) for name in dependencies
            )
        if module.startswith("agent."):
            assert not any(name.startswith("backend") for name in dependencies), module
            entry_points = {"agent.main", "agent.queue", "agent.batch"}
            assert not dependencies & entry_points, module
        elif module not in {"backend.worker", "backend.coordinator"}:
            assert not any(name.startswith("agent") for name in dependencies), module


def test_product_imports_have_no_cycles():
    modules = product_modules()
    graph = {name: imports(tree) & modules.keys() for name, tree in modules.items()}
    visited = set()

    def visit(name: str, chain: tuple[str, ...]) -> None:
        assert name not in chain, " -> ".join((*chain, name))
        if name in visited:
            return
        for dependency in graph[name]:
            visit(dependency, (*chain, name))
        visited.add(name)

    for name in graph:
        visit(name, ())


def test_agent_service_origins_live_in_configuration():
    for module, tree in product_modules().items():
        if not module.startswith("agent.") or module == "agent.config":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not node.value.startswith(("http://", "https://")), module
