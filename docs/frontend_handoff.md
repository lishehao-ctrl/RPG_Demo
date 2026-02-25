# Frontend Handoff Guide

## Active Pages
- `GET /demo/play`: player-facing runtime page.
- `GET /demo/dev`: developer diagnostics page.

`/demo/author` is removed.

## Stable Selector Contract
### Play
- `data-testid="play-shell"`
- `data-testid="play-story-select"`
- `data-testid="play-main"`
- `data-testid="play-stats-panel"`
- `data-testid="play-quest-panel"`
- `data-testid="play-run-panel"`
- `data-testid="play-impact-panel"`
- `data-testid="play-replay-drawer"`
- `data-testid="play-busy-indicator"`

### Dev
- `data-testid="dev-shell"`
- `data-testid="dev-session-panel"`
- `data-testid="dev-pending-panel"`
- `data-testid="dev-layer-inspector-panel"`
- `data-testid="dev-state-panel"`
- `data-testid="dev-timeline-panel"`
- `data-testid="dev-replay-panel"`

## Screenshot Regression Script
Use:
```bash
python scripts/capture_demo_screenshots.py --base-url http://127.0.0.1:8000 --out-dir artifacts/ui --tag local
```

The script validates play/dev only.
