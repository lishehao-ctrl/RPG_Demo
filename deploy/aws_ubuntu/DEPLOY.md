# AWS Ubuntu Deployment

This repo is deployable today on a single Ubuntu host in AWS.

Use this path for:

- one EC2 instance
- one backend process
- local SQLite files on persistent disk
- nginx serving the built frontend and reverse-proxying the backend

Important:

- these instructions are safe only when added as a dedicated RPG vhost on a host that may also run other apps
- do not remove unrelated nginx sites on a shared host
- current production shape uses backend port `8010`

Do not use a multi-worker backend process yet.

Current constraint:

- author job recovery and runtime state are persisted in SQLite
- the backend also spawns local resume threads for interrupted author jobs
- if you run multiple backend workers or multiple backend hosts against the same SQLite files, jobs can be resumed more than once

For now, production topology should be:

- `nginx`
- `uvicorn` single process
- one shared persistent disk path on the same machine

## Directory Layout

Recommended host layout:

```text
/srv/rpg-demo/
├── app/                 # checked-out repo
├── venv/                # python virtualenv
├── shared/
│   └── .env.production
└── data/
    ├── story_library.sqlite3
    └── runtime_state.sqlite3
```

## Instance Prerequisites

Install base packages:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

Preferred shared-host path:

- build the frontend locally
- sync the repo, including `frontend/dist`, to the server
- do not require Node/npm on the shared production host unless you explicitly choose on-host frontend builds

## App Setup

Clone the repo and prepare directories:

```bash
sudo mkdir -p /srv/rpg-demo
sudo chown -R ubuntu:ubuntu /srv/rpg-demo
cd /srv/rpg-demo
git clone <your-repo-url> app
mkdir -p shared data
python3 -m venv /srv/rpg-demo/venv
```

Install backend dependencies:

```bash
cd /srv/rpg-demo/app
/srv/rpg-demo/venv/bin/pip install -e ".[dev]"
```

Create the backend env file:

```bash
cp /srv/rpg-demo/app/deploy/aws_ubuntu/.env.production.example /srv/rpg-demo/shared/.env.production
```

Then edit `/srv/rpg-demo/shared/.env.production` and fill in the real Responses provider settings.

Minimum required values:

- `APP_RESPONSES_BASE_URL`
- `APP_RESPONSES_API_KEY`
- `APP_RESPONSES_MODEL`
- `APP_STORY_LIBRARY_DB_PATH`
- `APP_RUNTIME_STATE_DB_PATH`
- `APP_ENABLE_BENCHMARK_API=0`
- `APP_AUTH_SESSION_COOKIE_SECURE=true`
- `APP_AUTH_SESSION_COOKIE_SAMESITE=lax`

## Frontend Build

Preferred: build locally before upload.

If you intentionally build on the server, install Node/npm first and then run:

```bash
cd /srv/rpg-demo/app/frontend
npm ci
npm run build
```

Do not set `VITE_API_MODE=placeholder` in production.

For same-origin nginx serving, `VITE_API_BASE_URL` can stay unset.

## systemd Backend

Install the backend service:

```bash
sudo cp /srv/rpg-demo/app/deploy/aws_ubuntu/rpg-demo-backend.service /etc/systemd/system/rpg-demo-backend.service
sudo systemctl daemon-reload
sudo systemctl enable rpg-demo-backend
sudo systemctl start rpg-demo-backend
```

Check status:

```bash
sudo systemctl status rpg-demo-backend
journalctl -u rpg-demo-backend -n 100 --no-pager
```

## nginx

Install the nginx site additively:

```bash
sudo cp /srv/rpg-demo/app/deploy/aws_ubuntu/nginx-rpg-demo.conf /etc/nginx/sites-available/rpg-shehao-app
sudo ln -sf /etc/nginx/sites-available/rpg-shehao-app /etc/nginx/sites-enabled/rpg-shehao-app
sudo nginx -t
sudo systemctl reload nginx
```

On a shared host, do not remove existing site files that belong to other apps such as CalendarDIFF.

## Post-Deploy Checks

Backend health:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8010/health
```

Public same-origin health:

```bash
curl http://<your-domain-or-ip>/health
```

Real product smoke:

```bash
cd /srv/rpg-demo/app
/srv/rpg-demo/venv/bin/python tools/http_product_smoke.py --base-url http://127.0.0.1:8010
```

If you temporarily enable benchmark diagnostics in a non-public environment:

```bash
cd /srv/rpg-demo/app
/srv/rpg-demo/venv/bin/python tools/http_product_smoke.py \
  --base-url http://127.0.0.1:8010 \
  --include-benchmark-diagnostics
```

## Safe Update Procedure

```bash
cd /srv/rpg-demo/app
git pull
/srv/rpg-demo/venv/bin/pip install -e ".[dev]"
cd frontend
npm ci
npm run build
sudo systemctl restart rpg-demo-backend
sudo systemctl reload nginx
```

Then rerun:

```bash
cd /srv/rpg-demo/app
/srv/rpg-demo/venv/bin/python tools/http_product_smoke.py --base-url http://127.0.0.1:8010
```

## What Is Still Not Ready For Multi-Instance

These are the reasons to stay single-instance for now:

1. interrupted author jobs are resumed locally during backend startup
2. runtime state uses SQLite rather than a central database with distributed locking
3. play turn submission is not protected by cross-process session locking

If you later want multi-instance AWS deployment, the next step is:

- move runtime state and checkpoints off SQLite
- add distributed job/session locking
- then move to multiple backend workers or multiple hosts
