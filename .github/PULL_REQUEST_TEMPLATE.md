<!-- PR title: short, imperative, optionally prefixed (feat: / fix: / docs: / polish:) -->

## What this PR does

<!-- One paragraph. What user-visible or contributor-visible change
does this introduce? -->

## Why

<!-- Link to the issue this addresses, or describe the problem if
there's no issue. For mechanism / prompt changes, paste a before/
after example of LLM output. -->

## How to verify

<!-- Reproducible steps. If a deterministic test, just point at the
test file. If LLM behavior, paste sample I/O or attach a smoke
script's output. -->

## Checklist

- [ ] `pytest -q` passes
- [ ] `cd frontend2 && npm run check` passes
- [ ] If you added a contracts.py field, you mirrored it in `frontend2/src/api/contracts.ts`
- [ ] If you added a repository column, the migration is idempotent (gated by `existing_*_cols` check)
- [ ] If you changed an LLM prompt, you ran a manual smoke and the output looks correct
- [ ] You added a deterministic unit test for any new pure function (scheduler / parser / helper)
- [ ] You did not increase scope. (One feature per PR; one bugfix per PR.)
