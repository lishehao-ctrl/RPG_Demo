from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_URL = "http://127.0.0.1:5173"
DOC_CAPTURE_DIR = REPO_ROOT / "docs" / "demo-video" / "v2-captures"
REMOTION_CAPTURE_DIR = REPO_ROOT / "remotion-demo" / "public" / "captures"
FRAME_DIR = Path("/private/tmp/tiny_stories_admissions_typing_frames")
SEED = "At my wedding, the groom asks me to sign away my shares before the ceremony starts."
LIVE_SESSION_ID = "sess_adaa6563d733"
ENDING_SESSION_ID = "sess_965fb0758926"


def login(page, username: str) -> None:
    page.goto(f"{APP_URL}/#/login?next=create", wait_until="domcontentloaded")
    page.locator("input").first.fill(username)
    page.locator("button[type=submit]").click()
    page.wait_for_function("window.location.hash.includes('/create')", timeout=15_000)
    page.wait_for_selector("textarea", timeout=15_000)
    page.wait_for_timeout(500)


def copy_to_remotion(filename: str) -> None:
    shutil.copyfile(DOC_CAPTURE_DIR / filename, REMOTION_CAPTURE_DIR / filename)


def screenshot(page, filename: str, *, wait_ms: int = 700) -> None:
    page.wait_for_timeout(wait_ms)
    path = DOC_CAPTURE_DIR / filename
    page.screenshot(path=str(path), full_page=False, scale="device")
    copy_to_remotion(filename)


def capture_typing_video(page) -> None:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    for old in FRAME_DIR.glob("frame_*.png"):
        old.unlink()

    textarea = page.locator("textarea").first
    textarea.fill("")
    textarea.click()
    page.wait_for_timeout(300)

    frame = 0

    def save_frame() -> Path:
        nonlocal frame
        path = FRAME_DIR / f"frame_{frame:04d}.png"
        page.screenshot(path=str(path), full_page=False, scale="device")
        frame += 1
        return path

    first = save_frame()
    for _ in range(7):
        shutil.copyfile(first, FRAME_DIR / f"frame_{frame:04d}.png")
        frame += 1

    for char in SEED:
        page.keyboard.type(char)
        last = save_frame()
        if char in " ,.":  # tiny natural pause after word boundaries.
            shutil.copyfile(last, FRAME_DIR / f"frame_{frame:04d}.png")
            frame += 1

    final_frame = FRAME_DIR / f"frame_{frame - 1:04d}.png"
    shutil.copyfile(final_frame, DOC_CAPTURE_DIR / "02-create-seed-filled.png")
    copy_to_remotion("02-create-seed-filled.png")

    duration_seconds = 280 / 30
    source_seconds = frame / 18
    hold_seconds = max(0.1, duration_seconds - source_seconds)
    public_video = REMOTION_CAPTURE_DIR / "02-create-real-typing.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            "18",
            "-i",
            str(FRAME_DIR / "frame_%04d.png"),
            "-vf",
            f"scale=1920:1080:flags=lanczos,tpad=stop_mode=clone:stop_duration={hold_seconds:.3f}",
            "-r",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(public_video),
        ],
        check=True,
    )
    shutil.copyfile(public_video, DOC_CAPTURE_DIR / "02-create-real-typing.mp4")


def capture_live_session(page) -> None:
    page.goto(f"{APP_URL}/#/play/{LIVE_SESSION_ID}?reviewer=1", wait_until="domcontentloaded")
    page.wait_for_selector("text=Reviewer runtime inspector", timeout=20_000)
    screenshot(page, "03-play-runtime-top.png", wait_ms=900)

    page.evaluate("window.scrollTo(0, Math.max(0, document.body.scrollHeight * 0.28))")
    screenshot(page, "04-play-options-bottom.png", wait_ms=500)

    page.locator("button", has_text="Chat").last.click()
    page.wait_for_selector("text=Talk to your outsider friend", timeout=10_000)
    screenshot(page, "05-advisor-open.png", wait_ms=800)


def capture_ending_session(browser) -> None:
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=2,
        locale="en-US",
        color_scheme="dark",
    )
    page = context.new_page()
    login(page, "demo_user")
    page.goto(f"{APP_URL}/#/play/{ENDING_SESSION_ID}?reviewer=1", wait_until="domcontentloaded")
    page.wait_for_selector("text=Copy share link", timeout=20_000)
    screenshot(page, "06-ending-proof.png", wait_ms=900)
    context.close()


def main() -> None:
    DOC_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    REMOTION_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            locale="en-US",
            color_scheme="dark",
        )
        page = context.new_page()
        login(page, "portfolio_reviewer")

        page.goto(f"{APP_URL}/#/reviewer", wait_until="domcontentloaded")
        page.wait_for_selector("text=The Merger Betrayal", timeout=15_000)
        screenshot(page, "01-reviewer-entry.png")

        page.goto(f"{APP_URL}/#/create", wait_until="domcontentloaded")
        page.wait_for_selector("textarea", timeout=15_000)
        capture_typing_video(page)

        capture_live_session(page)

        page.goto(f"{APP_URL}/#/portfolio", wait_until="domcontentloaded")
        page.wait_for_selector("text=Tiny Stories is an inspectable AI drama runtime", timeout=15_000)
        screenshot(page, "07-portfolio-case-study.png", wait_ms=900)

        context.close()
        capture_ending_session(browser)
        browser.close()


if __name__ == "__main__":
    main()
