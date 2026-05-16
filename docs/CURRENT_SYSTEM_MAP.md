# Current System Map

This repository contains multiple generations of the RPG demo. The current
portfolio-facing product path is intentionally narrow:

```text
frontend2/                         current React app
  src/pages/home/                  plaza and recent runs
  src/pages/create/                signed-in story authoring
  src/pages/world/                 template detail + fork
  src/pages/play/                  playable session + reviewer inspector
  src/pages/replay/                public replay + fork CTA
  src/pages/portfolio/             admissions/reviewer entry points

rpg_backend/main.py                FastAPI route boundary, auth, quota guards
rpg_backend/narrative/             current template/session narrative runtime
  contracts.py                     Pydantic API contracts
  engine.py                        opening, turn, advisor, ending LLM boundary
  repository.py                    SQLite templates, sessions, messages
  service.py                       lifecycle and product metrics
rpg_backend/auth/                  username-only demo auth
rpg_backend/library/               older published-story library, still used by legacy play routes

docs/index.html                    GitHub Pages demo shell with embedded video
remotion-demo/                     programmatic portfolio video source
deploy/aws_ubuntu/                 single-instance deployment recipe
tools/narrative_release_gate.py    deterministic current-core release gate
tools/http_product_smoke.py        live HTTP smoke for /narrative/* routes
```

## Active User Flows

| Flow | Entry | Backend path | Notes |
| --- | --- | --- | --- |
| Reviewer demo | `#/portfolio` -> `#/reviewer` | `POST /narrative/templates` then `#/play/:id?reviewer=1` | Curated English seed, real session, inspector enabled. |
| Create story | `#/create` | `POST /narrative/templates` | Requires real session because it spends LLM budget and writes a template. |
| Play shared story | `#/template/:template_id` | `POST /narrative/templates/:id/sessions` | Anonymous play is allowed; forking a template does not call the LLM. |
| Advance turn | `#/play/:session_id` | `POST /narrative/sessions/:id/story/turns` | LLM quota guarded per IP and per user/default actor. |
| Advisor chat | Play sidebar | `POST /narrative/sessions/:id/advisor` | Side-channel reads context but does not mutate story state. |
| Share replay | `#/replay/:session_id` | `GET /narrative/sessions/:id/replay` | Public read-only replay includes `template_id` so viewers can fork the same story. |

## Legacy Or Experimental Surfaces

| Path | Status |
| --- | --- |
| `frontend/` | Older frontend retained for historical reference. Current builds and deployment use `frontend2/`. |
| `rpg_backend/author/` | Legacy author-job flow for the older published-story library. Public deployments can disable it with `APP_PUBLIC_DEMO_AUTHORING_ENABLED=false`. |
| `rpg_backend/play/` | Older published-story play runtime. Still covered by tests, but not the current portfolio path. |
| `rpg_backend/author_v2/`, `rpg_backend/author_v3/`, `rpg_backend/play_v2/` | Iteration layers used to develop mechanics, compilers, and evaluation ideas. |
| `specs/`, `stitch_handoff/`, `project/` | Design notes and handoff artifacts. Useful for provenance, not required to run the demo. |

## Current Test Gate

The default release gate is deterministic and does not spend LLM tokens:

```bash
python tools/narrative_release_gate.py --mode fake
python -m pytest -q
```

`tools/narrative_release_gate.py` exercises the current core directly:
template creation, public fork, four-turn playthrough, advisor side-chat,
ending synthesis, highlights, branches, public replay, and ending
distribution. When a real endpoint is configured, `tools/http_product_smoke.py`
runs the equivalent live HTTP path through `/narrative/*`.

## Production Boundary

The public demo is deliberately demo-grade:

- Username-only auth is used for portfolio friction, not account security.
- Anonymous visitors can browse public content, start/fork play sessions, and view replay links.
- Write paths require a real session: story/template creation, publishing, visibility changes, deletes, and `/me/*`.
- LLM calls are guarded by `APP_PUBLIC_DEMO_DAILY_IP_LLM_LIMIT` and `APP_PUBLIC_DEMO_DAILY_USER_LLM_LIMIT`; forwarded client IP headers are only trusted from `APP_TRUSTED_PROXY_IPS`.
- Benchmark diagnostics remain disabled unless `APP_ENABLE_BENCHMARK_API=1`.
- SQLite is supported for the single-process deployment described in `deploy/aws_ubuntu/DEPLOY.md`; multi-instance production would need shared locks and centralized counters.
