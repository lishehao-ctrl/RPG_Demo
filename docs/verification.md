# Verification

## Migration verification

1. Run migration:

```bash
DATABASE_URL=sqlite:///./tmp_verify.db alembic upgrade head
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
  - mapping boundaries (very positive vs very negative vectors)

### BranchEngine
- `tests/test_branch_engine.py`
  - threshold boundary (`gte` on exact boundary)
  - priority/exclusive resolution
  - default fallback path

### Session integration
- `tests/test_session_step_integration.py`
  - session step classification tags are persisted
  - affection deltas/rule hits persisted in action log
  - branch selected and persisted in dialogue node

### Snapshot/Rollback and token limit
- `tests/test_session_api.py`
  - create/get
  - snapshot/rollback exact restoration
  - rollback pruning nodes/logs after cutoff
  - token budget hard-limit error code stability
