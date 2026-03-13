# DB Migration Runbook

This runbook defines the manual migration workflow for backend services.

## Preconditions

- `APP_DATABASE_URL` points to the target PostgreSQL database.
- For production rollout, secret set also includes auth/runtime keys:
  - `APP_AUTH_JWT_SECRET`
  - `APP_ADMIN_BOOTSTRAP_EMAIL`
  - `APP_ADMIN_BOOTSTRAP_PASSWORD`
  - `APP_RESPONSES_BASE_URL`
  - `APP_RESPONSES_API_KEY`
  - `APP_RESPONSES_MODEL`
- Current deploy image contains the latest Alembic files.
- You can run repository scripts from the deploy environment.

## Local development

For local development, the default database is PostgreSQL via `compose.yaml` on `127.0.0.1:8132` (`rpg_dev` for app runtime, `rpg_test` for pytest).

Bring it up with:

```bash
docker compose up -d postgres
python scripts/db_migrate.py upgrade head
```

## Standard rollout flow

1. Check current and target revision:

```bash
python scripts/db_migrate.py current
python scripts/db_migrate.py heads
```

2. Apply migration:

```bash
python scripts/db_migrate.py upgrade head
```

3. Deploy backend and verify:

```bash
./scripts/k8s/k8s_verify_rollout.sh
```

## Rollback flow

1. Roll back application deployment first:

```bash
./scripts/k8s/k8s_rollback_last.sh
```

2. Evaluate whether database downgrade is required.
3. If required, run explicit downgrade revision:

```bash
python scripts/db_migrate.py downgrade <revision>
```

4. Re-run verification:

```bash
./scripts/k8s/k8s_verify_rollout.sh
```

## Common failures

1. `database_connection_failed`
- Verify `APP_DATABASE_URL`, network ACL, DB service health.

2. `schema_revision_missing`
- Database has no `alembic_version` entry. Run `upgrade head`.

3. `schema_revision_mismatch`
- DB revision is behind current code. Run `upgrade head` or deploy matching app revision.

4. Permission errors during migration
- Ensure DB role has DDL rights for schema migration.
