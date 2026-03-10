# UI Author/Play Playwright Regression - 2026-03-06

## Scope

This regression covered the real dual-track product:

- `Author Mode`: `/author/stories`, `/author/stories/:storyId`
- `Play Mode`: `/play/library`, `/play/sessions/:sessionId`

Environment used:

- backend: `http://127.0.0.1:8000`
- worker: `http://127.0.0.1:8100`
- frontend: `http://127.0.0.1:8173`
- live models:
  - `APP_LLM_OPENAI_MODEL=qwen-flash-us`
  - `APP_LLM_OPENAI_ROUTE_MODEL=qwen-plus-us`
  - `APP_LLM_OPENAI_NARRATION_MODEL=qwen-flash-us`
  - `APP_LLM_OPENAI_GENERATOR_MODEL=qwen-flash-us`

## Readiness

- backend `/ready`: `ready`
- worker `/ready`: `ready`
- no readiness failure observed during the run

## Main Flow Result

Status: `PASS`

Executed path:

1. opened the app and confirmed `Author` surface loaded
2. validated explicit `Sign Out -> Login -> redirect to /author/stories`
3. executed one `prompt` generation from `Author Mode`
4. opened generated draft detail
5. published the draft to `Play`
6. entered `Play Library`
7. created a session from the newly published story
8. executed one `free-text` turn in `Play Mode`
9. executed one `button` turn in `Play Mode`
10. refreshed the session page
11. confirmed session timeline/history rebuilt successfully

Generated prompt story:

- story id: `a2415f91-d9c9-47c5-b93d-74e9b16527e0`
- title: `Whispers in the Veil: A Forest City Under Siege`
- published version: `v1`

Created play session:

- session id: `c11fd175-af68-47ce-bb81-0726a9281fce`

## Branch Checks

### Prompt branch

Status: `PASS`

- `Generate Draft` from prompt succeeded
- draft detail loaded normally
- publish succeeded
- no `prompt_compile_failed` observed in this run

### Seed branch

Status: `PASS`

- generated a new seed-based draft from `Author Mode`
- generated story id: `fa57aa4c-59fb-4bd7-8dc2-d3cdce392d6d`
- draft detail loaded normally

## Play Runtime Checks

Status: `PASS`

- free-text first turn succeeded
- resulting `route_source` was `llm`
- button follow-up turn succeeded
- resulting `route_source` was `button`
- reload restored the existing session timeline

## Screenshots

Captured during the run:

- Author surface screenshot:
  - `var/folders/28/vsn0b5dn06vfpwckzzlqp__40000gn/T/playwright-mcp-output/1772769990208/page-2026-03-06T05-52-20-422Z.png`
- Play library screenshot:
  - `var/folders/28/vsn0b5dn06vfpwckzzlqp__40000gn/T/playwright-mcp-output/1772769990208/page-2026-03-06T05-54-12-214Z.png`

## Console / Failure Observation

- browser console did not show product-blocking UI errors in this run
- only informational React DevTools message was observed
- no worker queue timeout observed in this run
- no prompt compile failure observed in this run
- no unauthorized `/stories` console noise was observed in the validated author/play chain

## Conclusion

This run passed the intended medium-scale regression target:

- login path works
- author prompt generation works
- author seed generation works
- publish handoff into play works
- play session free-text and button actions work
- reload-safe history recovery works

Current result supports using the dual-track UI against the real DB-backed backend and real LLM worker for normal interactive testing.
