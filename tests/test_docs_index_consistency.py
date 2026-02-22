from __future__ import annotations

import re
from pathlib import Path


DOCS_DIR = Path("docs")
INDEX_PATH = DOCS_DIR / "INDEX.md"
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
INCLUDES_RE = re.compile(r"include[s]?\s+`([^`]+)`", re.IGNORECASE)


def test_docs_index_links_exist() -> None:
    text = INDEX_PATH.read_text(encoding="utf-8")
    for match in LINK_RE.finditer(text):
        link = match.group(1).strip()
        if not link or "://" in link or link.startswith("#"):
            continue
        path = (DOCS_DIR / link).resolve()
        assert path.exists(), f"docs/INDEX.md references missing file: {link}"


def test_docs_index_includes_claims_match_target_docs() -> None:
    lines = INDEX_PATH.read_text(encoding="utf-8").splitlines()
    current_target: Path | None = None
    for line in lines:
        link_match = LINK_RE.search(line)
        if link_match:
            link = link_match.group(1).strip()
            if link and "://" not in link and not link.startswith("#"):
                current_target = DOCS_DIR / link
        includes_match = INCLUDES_RE.search(line)
        if not includes_match or current_target is None:
            continue
        claim = includes_match.group(1).strip()
        target_text = current_target.read_text(encoding="utf-8")
        assert claim in target_text, (
            f"docs/INDEX.md claims '{claim}' is in {current_target}, "
            "but the phrase was not found."
        )
