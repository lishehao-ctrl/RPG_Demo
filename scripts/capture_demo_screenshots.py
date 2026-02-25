#!/usr/bin/env python3
"""Capture deterministic screenshots for /demo/play and /demo/dev.

This script is used as a PR acceptance gate for HUD UI changes.
It exits with non-zero status when critical UI/runtime checks fail.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urljoin

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import Page, sync_playwright
except Exception as exc:  # pragma: no cover - import guard for local setup
    raise SystemExit(
        "Playwright is not installed. Run: pip install -r requirements-dev-ui.txt"
    ) from exc


PLAY_SELECTORS = [
    '[data-testid="play-story-select"]',
    '[data-testid="play-shell"]',
    '[data-testid="play-main"]',
    '[data-testid="play-stats-panel"]',
    '[data-testid="play-quest-panel"]',
    '[data-testid="play-run-panel"]',
    '[data-testid="play-replay-drawer"]',
    '[data-testid="play-busy-indicator"]',
]

DEV_SELECTORS = [
    '[data-testid="dev-shell"]',
    '[data-testid="dev-session-panel"]',
    '[data-testid="dev-pending-panel"]',
    '[data-testid="dev-layer-inspector-panel"]',
    '[data-testid="dev-state-panel"]',
    '[data-testid="dev-timeline-panel"]',
    '[data-testid="dev-replay-panel"]',
]


def _norm_base_url(base_url: str) -> str:
    value = base_url.strip()
    if not value:
        raise ValueError("base-url cannot be empty")
    if not value.startswith("http://") and not value.startswith("https://"):
        value = f"http://{value}"
    if not value.endswith("/"):
        value += "/"
    return value


def _join(base_url: str, path: str) -> str:
    return urljoin(base_url, path.lstrip("/"))


def _probe_endpoint(url: str, timeout_s: float) -> tuple[bool, str]:
    req = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(req, timeout=timeout_s) as resp:
            status = int(resp.status or 0)
            if status >= 400:
                return False, f"HTTP {status}"
            return True, f"HTTP {status}"
    except urllib_error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib_error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return False, str(reason)
    except TimeoutError:
        return False, "timeout"


def _preflight_or_exit(base_url: str, timeout_s: float) -> None:
    targets = [
        ("/demo/play", "play page"),
        ("/demo/dev", "dev page"),
    ]

    failures: list[str] = []
    for path, label in targets:
        url = _join(base_url, path)
        ok, note = _probe_endpoint(url, timeout_s=timeout_s)
        if not ok:
            failures.append(f"- {label} {url} -> {note}")

    if not failures:
        return

    lines = [
        "Screenshot preflight failed: demo server is not reachable or not ready.",
        "Checks:",
        *failures,
        "",
        "Start the API first, then rerun screenshot capture:",
        "  ./scripts/dev.sh",
        "or",
        "  uvicorn app.main:app --reload",
    ]
    raise SystemExit("\n".join(lines))


def _expect_selector(
    page: Page,
    selector: str,
    timeout_ms: int = 15_000,
    *,
    state: str = "visible",
) -> None:
    page.wait_for_selector(selector, timeout=timeout_ms, state=state)


def _attach_guards(page: Page, issues: List[str], page_name: str) -> None:
    def on_page_error(error: BaseException) -> None:
        issues.append(f"{page_name}: uncaught JS error: {error}")

    def on_console(message) -> None:
        if message.type == "error":
            text = (message.text or "").strip()
            if text:
                issues.append(f"{page_name}: console error: {text}")

    def on_response(response) -> None:
        req = response.request
        resource_type = req.resource_type
        status = int(response.status)
        if status < 400:
            return
        if "favicon.ico" in response.url:
            return
        if resource_type in {"document", "script", "stylesheet"}:
            issues.append(
                f"{page_name}: resource HTTP {status} ({resource_type}) {response.url}"
            )

    def on_request_failed(request) -> None:
        failure = request.failure
        message = failure.get("errorText") if isinstance(failure, dict) else str(failure)
        issues.append(f"{page_name}: request failed: {request.url} :: {message}")

    page.on("pageerror", on_page_error)
    page.on("console", on_console)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)


def _capture_play(page: Page, base_url: str, out_dir: Path, issues: List[str]) -> None:
    page.goto(_join(base_url, "/demo/play"), wait_until="domcontentloaded", timeout=30_000)
    _expect_selector(page, '[data-testid="play-story-select"]')

    path_story_select = out_dir / "01_play_story_select.png"
    page.screenshot(path=path_story_select.as_posix(), full_page=True)

    card_count = page.locator(".story-card--button").count()
    if card_count < 1:
        issues.append(
            "play: no selectable story cards found. Seed at least one published/playable story first."
        )
        return

    page.locator(".story-card--button").first.click()
    page.click("#startStoryBtn")

    try:
        _expect_selector(page, "#playSection:not(.hidden)", timeout_ms=20_000)
    except PlaywrightError:
        issues.append("play: session did not enter playing state after clicking Start Selected Story")
        return
    for selector in PLAY_SELECTORS:
        if selector == '[data-testid="play-story-select"]':
            continue
        desired_state = "visible" if selector == '[data-testid="play-shell"]' else "attached"
        _expect_selector(page, selector, state=desired_state)

    path_playing = out_dir / "02_play_in_run.png"
    page.screenshot(path=path_playing.as_posix(), full_page=True)


def _pick_default_story(page: Page) -> tuple[str, str | None]:
    payload = page.evaluate(
        """
        async () => {
          const response = await fetch('/demo/bootstrap');
          if (!response.ok) {
            return { default_story_id: 'campus_week_v1', default_story_version: null };
          }
          return await response.json();
        }
        """
    )
    story_id = str(payload.get("default_story_id") or "campus_week_v1")
    version = payload.get("default_story_version")
    if version is None:
        return story_id, None
    return story_id, str(version)


def _capture_dev(page: Page, base_url: str, out_dir: Path, issues: List[str]) -> None:
    page.goto(_join(base_url, "/demo/dev"), wait_until="domcontentloaded", timeout=30_000)

    for selector in DEV_SELECTORS:
        _expect_selector(page, selector)

    path_console = out_dir / "03_dev_console.png"
    page.screenshot(path=path_console.as_posix(), full_page=True)

    story_id, version = _pick_default_story(page)
    page.fill("#storyId", story_id)
    if version is not None:
        page.fill("#storyVersion", version)
    else:
        page.fill("#storyVersion", "")

    page.click("#createSessionBtn")
    try:
        page.wait_for_function(
            "() => document.getElementById('sessionId')?.textContent?.trim() && document.getElementById('sessionId').textContent.trim() !== '(none)'",
            timeout=20_000,
        )
    except PlaywrightError:
        issues.append("dev: session creation did not complete in time")
        return

    path_created = out_dir / "04_dev_after_create.png"
    page.screenshot(path=path_created.as_posix(), full_page=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture UI screenshots for demo play/dev pages")
    parser.add_argument("--base-url", required=True, help="Base URL, for example http://127.0.0.1:8000")
    parser.add_argument("--out-dir", default="artifacts/ui", help="Output directory root")
    parser.add_argument("--tag", default="local", help="Output tag (sub-directory)")
    parser.add_argument("--probe-timeout-s", type=float, default=2.5, help="Preflight probe timeout seconds")
    args = parser.parse_args()

    base_url = _norm_base_url(args.base_url)
    _preflight_or_exit(base_url, timeout_s=max(0.5, float(args.probe_timeout_s)))

    out_dir = Path(args.out_dir).resolve() / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    issues: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1024})
        play_page = context.new_page()
        dev_page = context.new_page()

        _attach_guards(play_page, issues, "play")
        _attach_guards(dev_page, issues, "dev")

        _capture_play(play_page, base_url, out_dir, issues)
        _capture_dev(dev_page, base_url, out_dir, issues)

        context.close()
        browser.close()

    if issues:
        print("Screenshot capture failed with guard violations:")
        for idx, issue in enumerate(issues, start=1):
            print(f"{idx}. {issue}")
        return 1

    print(f"Screenshots written to: {out_dir}")
    print("- 01_play_story_select.png")
    print("- 02_play_in_run.png")
    print("- 03_dev_console.png")
    print("- 04_dev_after_create.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
