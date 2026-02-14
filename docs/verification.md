# Verification

## Migration verification

1. Run migration:

```bash
DATABASE_URL=sqlite:///./manual_m5.db alembic upgrade head
```

Expected: command exits 0 and creates all required tables.

2. Run tests:

```bash
pytest -q
```

## Milestone 4 verification

### AffectionEngine
- `tests/test_affection_engine.py`
  - saturation / clamp bounds
  - drift decay
  - determinism for same input/state
  - mapping boundaries

### BranchEngine
- `tests/test_branch_engine.py`
  - threshold boundary (`gte` on exact boundary)
  - priority/exclusive resolution
  - default fallback path
  - trace contains `actual_value` and expected threshold

### Session integration
- `tests/test_session_step_integration.py`
  - session step classification tags are persisted
  - affection deltas/rule hits persisted in action log
  - branch selection persisted
  - branch evaluation stores all candidates with trace

## Milestone 5 verification

### ReplayEngine deterministic report
- `tests/test_replay_engine.py`
  - create session, run controlled steps, call `/end`, call `/replay`
  - assert replay contains required top-level keys
  - assert repeated `/replay` calls return identical JSON
  - assert direct `ReplayEngine.build_report(...)` equals stored report

### Missed routes and near-miss hints
- `tests/test_replay_engine.py`
  - seed multiple matched branches and verify lower-priority match appears in `missed_routes` with reason `priority lost`
  - seed threshold-failing branch and verify `unlock_hint` includes threshold guidance (e.g., trust `>=`)

### End idempotency and replay upsert
- `tests/test_replay_engine.py`
  - call `/sessions/{id}/end` twice
  - assert same `route_type`, same `replay_report_id`, and single `replay_reports` row

### Snapshot/Rollback and token limit
- `tests/test_session_api.py`
  - create/get
  - snapshot/rollback exact restoration
  - rollback pruning nodes/logs after cutoff
  - token budget hard-limit error code stability
