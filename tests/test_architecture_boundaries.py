from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.modules.story import router as story_router
from app.modules.story import schemas as story_schemas
from app.modules.story import service_api as story_service_api
from app.modules.session import service as session_service


def _module_tree(module) -> ast.Module:
    source = inspect.getsource(module)
    return ast.parse(source)


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
        "validate_author_story_pack",
        "compile_author_story_pack",
        "author_assist",
        "store_story_pack",
        "list_story_packs",
        "get_story_pack",
        "publish_story_pack",
    ]

    source = inspect.getsource(story_router)
    assert "def _friendly_story_error" not in source
    assert "def compile_author_payload_with_runtime_checks" not in source


def test_story_schema_and_service_modules_exist() -> None:
    assert hasattr(story_schemas, "StoryPack")
    assert hasattr(story_schemas, "AuthorAssistRequest")
    assert hasattr(story_service_api, "story_pack_errors")
    assert hasattr(story_service_api, "compile_author_payload_with_runtime_checks")


def test_authoring_module_remains_v4_only() -> None:
    authoring_dir = Path("app/modules/story/authoring")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in authoring_dir.glob("*.py"))
    forbidden = [
        "compile_author_story_payload_v2",
        "compile_author_story_payload_v3",
        "author_v2_required_message",
        "author_v3_required_message",
        "_project_v4_to_v3_payload",
        "_project_v3_to_v2_payload",
    ]
    for symbol in forbidden:
        assert symbol not in combined


def test_session_service_delegates_to_extracted_modules() -> None:
    source = inspect.getsource(session_service)
    assert "from app.modules.session import debug_views" in source
    assert "from app.modules.session import" in source
    assert "return runtime_pack.normalize_pack_for_runtime(pack_json)" in source
    assert "return runtime_fallback.resolve_runtime_fallback(node, current_node_id, node_ids)" in source
    assert "return debug_views.get_llm_trace(db, session_id, limit=limit)" in source
    assert "return debug_views.get_layer_inspector(db, session_id, limit=limit)" in source
