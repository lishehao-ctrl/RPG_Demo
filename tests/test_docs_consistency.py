from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"

REQUIRED_DOCS = {
    "architecture.md",
    "runtime_status.md",
    "deployment_probes.md",
    "db_migration_runbook.md",
    "oncall_sop.md",
    "prompt_authoring_structure.md",
}

FORBIDDEN_DOC_FILES = {
    "architecture_story_runtime.md",
    "story_architecture_v3.md",
}

FORBIDDEN_REFERENCES = {
    "docs/architecture_story_runtime.md",
    "docs/story_architecture_v3.md",
    "story_architecture_v3.md",
    "architecture_story_runtime.md",
}

REQUIRED_SECURITY_MARKERS = {
    "README.md": {"APP_AUTH_JWT_SECRET", "APP_INTERNAL_WORKER_TOKEN", "/admin/auth/login"},
    "docs/deployment_probes.md": {"APP_AUTH_JWT_SECRET", "APP_INTERNAL_WORKER_TOKEN"},
    "docs/db_migration_runbook.md": {"APP_AUTH_JWT_SECRET", "APP_INTERNAL_WORKER_TOKEN"},
    "docs/runtime_status.md": {"APP_INTERNAL_WORKER_TOKEN", "/admin/auth/login"},
    "docs/architecture.md": {"APP_INTERNAL_WORKER_TOKEN", "/admin/auth/login"},
}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_docs_exist_and_forbidden_docs_removed() -> None:
    existing_docs = {p.name for p in DOCS_ROOT.glob("*.md")}
    missing = sorted(REQUIRED_DOCS - existing_docs)
    forbidden_present = sorted(FORBIDDEN_DOC_FILES & existing_docs)

    assert not missing, f"missing required docs: {missing}"
    assert not forbidden_present, f"forbidden docs still present: {forbidden_present}"


def test_no_forbidden_doc_references_in_readme_and_docs() -> None:
    scan_paths = [REPO_ROOT / "README.md", *sorted(DOCS_ROOT.glob("*.md"))]
    violations: list[str] = []

    for path in scan_paths:
        content = _read_text(path)
        for marker in FORBIDDEN_REFERENCES:
            if marker in content:
                rel = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel}: contains forbidden reference '{marker}'")

    assert not violations, "forbidden doc references found:\n" + "\n".join(sorted(violations))


def test_security_markers_present_in_core_docs() -> None:
    violations: list[str] = []

    for rel_path, markers in REQUIRED_SECURITY_MARKERS.items():
        path = REPO_ROOT / rel_path
        content = _read_text(path)
        for marker in markers:
            if marker not in content:
                violations.append(f"{rel_path}: missing required marker '{marker}'")

    assert not violations, "security marker coverage failures:\n" + "\n".join(sorted(violations))
