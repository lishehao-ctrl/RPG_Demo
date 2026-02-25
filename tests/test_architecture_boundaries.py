from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.modules.story import router as story_router
from app.modules.story import schemas as story_schemas
from app.modules.story import service_api as story_service_api
from app.modules.session import service as session_service
from app.modules.session import runtime_pack as session_runtime_pack


def _module_tree(module) -> ast.Module:
    source = inspect.getsource(module)
    return ast.parse(source)


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imports_llm_module(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = str(alias.name or "")
                if name == "app.modules.llm" or name.startswith("app.modules.llm."):
                    return True
        if isinstance(node, ast.ImportFrom):
            module = str(node.module or "")
            if module == "app.modules.llm" or module.startswith("app.modules.llm."):
                return True
    return False


def test_story_router_is_http_layer_only() -> None:
    tree = _module_tree(story_router)
    class_defs = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    assert class_defs == []

    function_defs = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert function_defs == [
        "validate_story_pack",
        "list_story_packs",
        "get_story_pack",
    ]

    source = inspect.getsource(story_router)
    assert "def _friendly_story_error" not in source
    assert "def compile_author_payload_with_runtime_checks" not in source


def test_story_schema_and_service_modules_exist() -> None:
    assert hasattr(story_schemas, "StoryPack")
    assert hasattr(story_service_api, "story_pack_errors")
    assert hasattr(session_runtime_pack, "validate_runtime_pack_v10_strict")


def test_story_pack_schema_hard_cuts_legacy_author_source_v3() -> None:
    source = inspect.getsource(story_schemas)
    assert "author_source_v3" not in source
    assert "author_source_v4" in source


def test_forbidden_modules_do_not_import_llm() -> None:
    forbidden_roots = [
        Path("app/modules/narrative"),
    ]
    offenders: list[str] = []
    for root in forbidden_roots:
        for path in _python_files(root):
            if _imports_llm_module(path):
                offenders.append(path.as_posix())

    service_api_path = Path("app/modules/story/service_api.py")
    if _imports_llm_module(service_api_path):
        offenders.append(service_api_path.as_posix())

    assert offenders == [], f"LLM imports leaked into deterministic modules: {offenders}"


def test_llm_touchpoints_are_limited_to_whitelist() -> None:
    scoped_roots = [Path("app/modules/session"), Path("app/modules/story")]
    actual: set[str] = set()
    for root in scoped_roots:
        for path in _python_files(root):
            if _imports_llm_module(path):
                actual.add(path.as_posix())

    expected = {
        "app/modules/session/selection.py",
        "app/modules/session/service.py",
        "app/modules/session/story_runtime/pipeline.py",
    }
    assert actual == expected, f"Unexpected LLM touchpoints: {sorted(actual)}"


def test_session_service_delegates_to_extracted_modules() -> None:
    source = inspect.getsource(session_service)
    assert "from app.modules.session import debug_views" in source
    assert "runtime_deps" in source
    assert "runtime_orchestrator" in source
    assert "return runtime_deps.normalize_pack_for_runtime(pack_json)" in source
    assert "return runtime_orchestrator.run_story_runtime_step(" in source
    assert "return debug_views.get_layer_inspector(db, session_id, limit=limit)" in source
