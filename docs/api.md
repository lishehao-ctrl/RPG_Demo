# API Surface

## Health
- `GET /health`

## Demo Pages
- `GET /demo` -> redirects to `/demo/play`
- `GET /demo/play`
- `GET /demo/dev`
- `GET /demo/bootstrap`

`GET /demo/author` has been removed.

## Story APIs
- `POST /stories/validate`
- `GET /stories`
- `GET /stories/{story_id}`

Story write APIs removed:
- `POST /stories`
- `POST /stories/{story_id}/publish`

Authoring APIs removed:
- `POST /stories/validate-author`
- `POST /stories/compile-author`
- `POST /stories/author-assist`
- `POST /stories/author-assist/stream`
- `POST /stories/author-assist/ingest-file`
- `POST /stories/author-assist/ingest-file/stream`

## Session APIs
- `POST /sessions`
- `GET /sessions/{id}`
- `POST /sessions/{id}/step`
- `POST /sessions/{id}/step/stream`
- `POST /sessions/{id}/rollback`
- `GET /sessions/{id}/debug/*` (dev only)

## Offline Story Seeding
Use `scripts/seed.py` to write/publish story packs directly to DB:

```bash
python scripts/seed.py --story-file examples/storypacks/campus_week_v1.json --publish
```
