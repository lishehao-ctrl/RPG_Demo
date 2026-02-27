from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


_REQUIRED_TRACKED_PATHS = [
    "app/main.py",
    "requirements.txt",
    "app/config.py",
    "app/db/models.py",
    "app/modules/story_domain/schemas.py",
    "app/utils/time.py",
]


def test_requirements_manifest_exists_and_non_empty() -> None:
    req = REPO_ROOT / "requirements.txt"
    assert req.exists(), "requirements.txt must exist"
    assert req.stat().st_size > 0, "requirements.txt must not be empty"


def test_app_entrypoint_module_importable() -> None:
    importlib.import_module("app.main")


def test_story_domain_service_importable() -> None:
    importlib.import_module("app.modules.story_domain.service")


def test_required_runtime_paths_are_tracked_by_git() -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("git metadata not available in this environment")

    for rel_path in _REQUIRED_TRACKED_PATHS:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel_path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"required path is not tracked: {rel_path}"
