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

AUTHOR_SELECTORS = [
    '#continueWriteBtn',
    '#authorLlmFeedback',
    '#authorStoryOverviewList',
]

AUTHOR_STAGE_CLASSES = [
    "assist-stage--requesting",
    "assist-stage--building",
    "assist-stage--retrying",
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


def _preflight_or_exit(base_url: str, timeout_s: float, *, check_author_animation: bool = False) -> None:
    targets = [
        ("/demo/play", "play page"),
        ("/demo/dev", "dev page"),
    ]
    if check_author_animation:
        targets.append(("/demo/author", "author page"))

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


def _install_author_stream_mock(page: Page) -> None:
    page.add_init_script(
        """
        (() => {
          const originalFetch = window.fetch.bind(window);
          const encoder = new TextEncoder();

          function sseBlock(eventName, payload) {
            return `event: ${eventName}\\ndata: ${JSON.stringify(payload)}\\n\\n`;
          }

          window.fetch = async (input, init) => {
            const requestUrl = typeof input === "string" ? input : (input?.url || "");
            const inputMethod = typeof input === "object" && input ? input.method : null;
            const method = String(init?.method || inputMethod || "GET").toUpperCase();

            if (method === "POST" && /\\/stories\\/author-assist\\/stream(?:\\?|$)/.test(requestUrl)) {
              const chunks = [
                sseBlock("stage", {
                  stage_code: "author.expand.start",
                  label: "Sending first continuation request...",
                  task: "continue_write",
                  request_kind: "author_assist",
                }),
                sseBlock("stage", {
                  stage_code: "llm.retry",
                  label: "Retrying request...",
                  task: "continue_write",
                  request_kind: "author_assist",
                }),
                sseBlock("stage", {
                  stage_code: "author.build.start",
                  label: "Sending full story architecture request...",
                  task: "continue_write",
                  request_kind: "author_assist",
                  overview_source: "author_idea_blueprint_v1",
                  overview_rows: [
                    {
                      label: "Core Conflict",
                      value: "student vs roommate | resource scholarship | deadline one week | risk lose funding",
                    },
                    {
                      label: "Tension Loop",
                      value: "pressure_open (r3) -> pressure_escalation (r4) -> recovery_window (r2) -> decision_gate (r5)",
                    },
                    {
                      label: "Branch Contrast",
                      value: "high-risk study push vs recovery rest stabilize",
                    },
                    {
                      label: "Lexical Anchors",
                      value: "must include: roommate, scholarship | avoid generic: Option A",
                    },
                    {
                      label: "Task Focus",
                      value: "Append a follow-up beat while preserving conflict contrast.",
                    },
                  ],
                }),
                sseBlock("result", {
                  suggestions: {
                    story_overview: [
                      "Escalate pressure while preserving one recovery branch.",
                    ],
                  },
                  patch_preview: [
                    {
                      id: "patch_stage_demo",
                      label: "Refine next escalation beat",
                      path: "/plot/mainline_goal",
                      value: "Keep rising pressure and preserve one safe branch.",
                    },
                  ],
                  warnings: [],
                  model: "mock-stage-model",
                }),
              ];
              const delays = [120, 540, 540, 540];
              const stream = new ReadableStream({
                start(controller) {
                  let index = 0;
                  function pushNext() {
                    if (index >= chunks.length) {
                      controller.close();
                      return;
                    }
                    controller.enqueue(encoder.encode(chunks[index]));
                    const waitMs = Number(delays[index] || 0);
                    index += 1;
                    window.setTimeout(pushNext, waitMs);
                  }
                  pushNext();
                },
              });

              return new Response(stream, {
                status: 200,
                headers: {
                  "Content-Type": "text/event-stream",
                  "Cache-Control": "no-cache",
                },
              });
            }

            return originalFetch(input, init);
          };
        })();
        """
    )


def _wait_for_author_stage(
    page: Page,
    *,
    expected_class: str,
    expected_button_text: str,
    expected_feedback_text: str,
    timeout_ms: int = 8_000,
) -> None:
    page.wait_for_function(
        """
        (payload) => {
          const button = document.getElementById('continueWriteBtn');
          const feedback = document.getElementById('authorLlmFeedback');
          if (!button || !feedback) return false;
          const buttonText = String(button.textContent || '').trim();
          const feedbackText = String(feedback.textContent || '').trim();
          return button.classList.contains(payload.expectedClass)
            && buttonText.includes(payload.expectedButtonText)
            && feedbackText.includes(payload.expectedFeedbackText);
        }
        """,
        arg={
            "expectedClass": expected_class,
            "expectedButtonText": expected_button_text,
            "expectedFeedbackText": expected_feedback_text,
        },
        timeout=timeout_ms,
    )


def _capture_author_animation(page: Page, base_url: str, out_dir: Path, issues: List[str]) -> None:
    _install_author_stream_mock(page)
    page.goto(_join(base_url, "/demo/author"), wait_until="domcontentloaded", timeout=30_000)

    for selector in AUTHOR_SELECTORS:
        desired_state = "attached" if selector == "#authorLlmFeedback" else "visible"
        _expect_selector(page, selector, state=desired_state)

    page.fill("#authorSeedInput", "A student faces mounting deadline pressure.")
    page.fill("#authorContinueInput", "Continue with one new high-pressure beat.")
    page.click("#continueWriteBtn")

    try:
        _wait_for_author_stage(
            page,
            expected_class="assist-stage--requesting",
            expected_button_text="Sending first continuation request...",
            expected_feedback_text="Sending first continuation request...",
        )
    except PlaywrightError:
        issues.append(
            "author: missing requesting stage (assist-stage--requesting / Sending first continuation request...)"
        )
        return
    page.screenshot(path=(out_dir / "05_author_stage_requesting.png").as_posix(), full_page=True)

    try:
        _wait_for_author_stage(
            page,
            expected_class="assist-stage--retrying",
            expected_button_text="Retrying request...",
            expected_feedback_text="Retrying request...",
        )
    except PlaywrightError:
        issues.append("author: missing retry stage (assist-stage--retrying / Retrying request...)")
        return

    try:
        _wait_for_author_stage(
            page,
            expected_class="assist-stage--building",
            expected_button_text="Sending full story architecture request...",
            expected_feedback_text="Sending full story architecture request...",
        )
    except PlaywrightError:
        issues.append(
            "author: missing building stage (assist-stage--building / Sending full story architecture request...)"
        )
        return
    try:
        page.wait_for_function(
            """
            (payload) => {
              const list = document.getElementById('authorStoryOverviewList');
              if (!list) return false;
              const text = String(list.textContent || '');
              return payload.requiredPhrases.every((phrase) => text.includes(phrase));
            }
            """,
            arg={
                "requiredPhrases": [
                    "The core conflict now centers on",
                    "student vs roommate",
                ]
            },
            timeout=8_000,
        )
    except PlaywrightError:
        issues.append("author: Story Overview did not update with first-pass expansion content before build screenshot")
        return
    page.screenshot(path=(out_dir / "06_author_stage_building.png").as_posix(), full_page=True)

    try:
        page.wait_for_function(
            """
            (payload) => {
              const button = document.getElementById('continueWriteBtn');
              if (!button) return false;
              const hasStageClass = payload.stageClasses.some((name) => button.classList.contains(name));
              const buttonText = String(button.textContent || '').trim();
              return !hasStageClass && buttonText === payload.expectedIdleText && button.disabled === false;
            }
            """,
            arg={"stageClasses": AUTHOR_STAGE_CLASSES, "expectedIdleText": "Continue Write"},
            timeout=10_000,
        )
    except PlaywrightError:
        issues.append("author: stage classes were not cleared or Continue Write button did not return to idle")
        return
    page.screenshot(path=(out_dir / "07_author_stage_done.png").as_posix(), full_page=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture UI screenshots for demo play/dev pages")
    parser.add_argument("--base-url", required=True, help="Base URL, for example http://127.0.0.1:8000")
    parser.add_argument("--out-dir", default="artifacts/ui", help="Output directory root")
    parser.add_argument("--tag", default="local", help="Output tag (sub-directory)")
    parser.add_argument("--probe-timeout-s", type=float, default=2.5, help="Preflight probe timeout seconds")
    parser.add_argument(
        "--check-author-animation",
        action="store_true",
        help="Run optional Author stage animation E2E checks and capture stage screenshots",
    )
    args = parser.parse_args()

    base_url = _norm_base_url(args.base_url)
    _preflight_or_exit(
        base_url,
        timeout_s=max(0.5, float(args.probe_timeout_s)),
        check_author_animation=bool(args.check_author_animation),
    )

    out_dir = Path(args.out_dir).resolve() / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    issues: List[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1024})
        play_page = context.new_page()
        dev_page = context.new_page()
        author_page = context.new_page() if args.check_author_animation else None

        _attach_guards(play_page, issues, "play")
        _attach_guards(dev_page, issues, "dev")
        if author_page is not None:
            _attach_guards(author_page, issues, "author")

        _capture_play(play_page, base_url, out_dir, issues)
        _capture_dev(dev_page, base_url, out_dir, issues)
        if author_page is not None:
            _capture_author_animation(author_page, base_url, out_dir, issues)

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
    if args.check_author_animation:
        print("- 05_author_stage_requesting.png")
        print("- 06_author_stage_building.png")
        print("- 07_author_stage_done.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
