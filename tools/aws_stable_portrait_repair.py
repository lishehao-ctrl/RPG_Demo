from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_HOST = "ubuntu@54.152.242.119"
DEFAULT_KEY_PATH = Path.home() / ".ssh" / "aws-main.pem"
DEFAULT_REMOTE_APP_DIR = "/srv/rpg-demo/app"
DEFAULT_REMOTE_DATA_DIR = "/srv/rpg-demo/data"
DEFAULT_REMOTE_ENV_PATH = "/srv/rpg-demo/shared/.env.production"
DEFAULT_PUBLIC_BASE_URL = "https://rpg.shehao.app"
DEFAULT_LOCAL_PORTRAIT_DIR = Path("artifacts/portraits/roster")


@dataclass(frozen=True)
class RepairConfig:
    host: str
    key_path: Path
    public_base_url: str
    api_base_url: str
    remote_app_dir: str
    remote_data_dir: str
    remote_env_path: str
    local_portrait_dir: Path

    @property
    def remote_roster_portrait_dir(self) -> str:
        return f"{self.remote_app_dir}/artifacts/portraits/roster"

    @property
    def remote_author_job_portrait_dir(self) -> str:
        return f"{self.remote_app_dir}/artifacts/portraits/author_jobs"

    @property
    def remote_runtime_catalog_path(self) -> str:
        return f"{self.remote_data_dir}/character_roster_runtime.json"

    @property
    def remote_nginx_site_path(self) -> str:
        return "/etc/nginx/sites-available/rpg-shehao-app"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair portrait assets for the AWS stable deployment.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--host", default=DEFAULT_HOST)
        subparser.add_argument("--key-path", type=Path, default=DEFAULT_KEY_PATH)
        subparser.add_argument("--public-base-url", default=DEFAULT_PUBLIC_BASE_URL)
        subparser.add_argument("--api-base-url", default=DEFAULT_PUBLIC_BASE_URL)
        subparser.add_argument("--remote-app-dir", default=DEFAULT_REMOTE_APP_DIR)
        subparser.add_argument("--remote-data-dir", default=DEFAULT_REMOTE_DATA_DIR)
        subparser.add_argument("--remote-env-path", default=DEFAULT_REMOTE_ENV_PATH)
        subparser.add_argument("--local-portrait-dir", type=Path, default=DEFAULT_LOCAL_PORTRAIT_DIR)

    add_common(subparsers.add_parser("repair", help="Sync portraits, rewrite runtime catalog, and deploy nginx config."))
    add_common(subparsers.add_parser("verify", help="Verify portrait assets, catalog URLs, and HTTP responses."))

    replace = subparsers.add_parser("replace-story", help="Re-generate and republish one existing story using its original prompt seed.")
    add_common(replace)
    replace.add_argument("--story-id", required=True)
    replace.add_argument("--visibility", choices=("private", "public"), default="private")
    replace.add_argument("--request-timeout-seconds", type=float, default=120.0)
    replace.add_argument("--poll-timeout-seconds", type=float, default=300.0)
    replace.add_argument("--poll-interval-seconds", type=float, default=2.0)
    return parser.parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> RepairConfig:
    return RepairConfig(
        host=str(args.host),
        key_path=Path(args.key_path).expanduser().resolve(),
        public_base_url=str(args.public_base_url).rstrip("/"),
        api_base_url=str(args.api_base_url).rstrip("/"),
        remote_app_dir=str(args.remote_app_dir).rstrip("/"),
        remote_data_dir=str(args.remote_data_dir).rstrip("/"),
        remote_env_path=str(args.remote_env_path),
        local_portrait_dir=Path(args.local_portrait_dir).expanduser().resolve(),
    )


def _run(command: list[str], *, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def _ssh_base(config: RepairConfig) -> list[str]:
    return ["ssh", "-i", str(config.key_path), "-o", "StrictHostKeyChecking=no", config.host]


def _scp_base(config: RepairConfig) -> list[str]:
    return ["scp", "-i", str(config.key_path), "-o", "StrictHostKeyChecking=no"]


def run_ssh(config: RepairConfig, remote_command: str) -> str:
    result = _run([*_ssh_base(config), remote_command])
    return result.stdout


def run_scp(config: RepairConfig, source: str, target: str) -> None:
    _run([*_scp_base(config), source, target], capture_output=True)


def run_rsync(config: RepairConfig, source_dir: Path, target_dir: str) -> None:
    _run(
        [
            "rsync",
            "-az",
            "--delete",
            "-e",
            f"ssh -i {config.key_path} -o StrictHostKeyChecking=no",
            f"{source_dir}/",
            f"{config.host}:{target_dir}/",
        ],
        capture_output=True,
    )


def local_portrait_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("current.png") if path.is_file())


def _remote_python(config: RepairConfig, script: str) -> str:
    quoted = "python3 - <<'PY'\n" + script + "\nPY"
    return run_ssh(config, quoted)


def _backup_remote_runtime_catalog(config: RepairConfig) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = f"{config.remote_data_dir}/backups/character_roster_runtime_{timestamp}.json"
    run_ssh(
        config,
        (
            f"mkdir -p {config.remote_data_dir}/backups && "
            f"cp {config.remote_runtime_catalog_path} {backup_path}"
        ),
    )
    return backup_path


def _remote_env_value(config: RepairConfig, key: str) -> str | None:
    output = run_ssh(
        config,
        (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"env_path = Path({config.remote_env_path!r})\n"
            f"key = {key!r}\n"
            "value = None\n"
            "if env_path.exists():\n"
            "    for raw_line in env_path.read_text().splitlines():\n"
            "        line = raw_line.strip()\n"
            "        if not line or line.startswith('#') or '=' not in line:\n"
            "            continue\n"
            "        left, right = line.split('=', 1)\n"
            "        if left.strip() == key:\n"
            "            value = right.strip()\n"
            "            break\n"
            "print(value or '')\n"
            "PY"
        ),
    ).strip()
    return output or None


def _resolved_remote_story_library_path(config: RepairConfig) -> str:
    return _remote_env_value(config, "APP_STORY_LIBRARY_DB_PATH") or f"{config.remote_app_dir}/artifacts/story_library.sqlite3"


def _rewrite_runtime_catalog(config: RepairConfig) -> str:
    script = f"""
import json
from pathlib import Path

base_url = {config.public_base_url!r}.rstrip("/")
path = Path({config.remote_runtime_catalog_path!r})
payload = json.loads(path.read_text())
entries = payload.get("entries") or []
for entry in entries:
    character_id = str(entry.get("character_id") or "").strip()
    if not character_id:
        continue
    portrait_variants = entry.get("portrait_variants") or {{}}
    rebuilt_variants = {{}}
    source_variants = set(portrait_variants.keys()) if isinstance(portrait_variants, dict) else set()
    if not source_variants:
        source_variants = {{"neutral", "negative", "positive"}}
    for variant in sorted(source_variants):
        rebuilt_variants[variant] = f"{{base_url}}/portraits/roster/{{character_id}}/{{variant}}/current.png"
    entry["portrait_variants"] = rebuilt_variants
    entry["portrait_url"] = rebuilt_variants.get("neutral")
    entry["default_portrait_url"] = rebuilt_variants.get("neutral")
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n")
print(path)
"""
    return _remote_python(config, script).strip()


def _rewrite_published_story_portrait_urls(config: RepairConfig) -> dict[str, Any]:
    story_library_path = _resolved_remote_story_library_path(config)
    script = f"""
import json
import sqlite3

db_path = {story_library_path!r}
old_prefix = "http://127.0.0.1:8000/portraits/roster/"
new_prefix = {config.public_base_url!r}.rstrip("/") + "/portraits/roster/"

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT story_id, preview_json, bundle_json FROM published_stories")
updated_story_ids = []
for story_id, preview_json, bundle_json in cur.fetchall():
    preview_text = str(preview_json)
    bundle_text = str(bundle_json)
    if old_prefix not in preview_text and old_prefix not in bundle_text:
        continue
    preview_text = preview_text.replace(old_prefix, new_prefix)
    bundle_text = bundle_text.replace(old_prefix, new_prefix)
    cur.execute(
        "UPDATE published_stories SET preview_json = ?, bundle_json = ? WHERE story_id = ?",
        (preview_text, bundle_text, story_id),
    )
    updated_story_ids.append(story_id)
conn.commit()
print(json.dumps({{"db_path": db_path, "updated_story_ids": updated_story_ids}}, ensure_ascii=False))
"""
    return json.loads(_remote_python(config, script))


def _remote_file_count(config: RepairConfig, directory: str) -> int:
    output = run_ssh(config, f"find {directory} -type f -name current.png | wc -l")
    return int(output.strip() or "0")


def _deploy_nginx_config(config: RepairConfig) -> None:
    local_template = Path("deploy/aws_ubuntu/nginx-rpg-demo.conf").resolve()
    remote_tmp = f"/tmp/nginx-rpg-demo.conf"
    run_scp(config, str(local_template), f"{config.host}:{remote_tmp}")
    run_ssh(
        config,
        (
            f"sudo cp {remote_tmp} {config.remote_nginx_site_path} && "
            "sudo nginx -t && "
            "sudo systemctl reload nginx"
        ),
    )


def _restart_backend(config: RepairConfig) -> None:
    run_ssh(config, "sudo systemctl restart rpg-demo-backend")


def _verify_catalog_base_url(config: RepairConfig) -> dict[str, Any]:
    script = f"""
import json
from pathlib import Path
path = Path({config.remote_runtime_catalog_path!r})
payload = json.loads(path.read_text())
entries = payload.get("entries") or []
localhost_hits = []
sample_urls = []
for entry in entries[:5]:
    sample_urls.append(entry.get("portrait_url"))
for entry in entries:
    text = json.dumps(entry, ensure_ascii=False)
    if "127.0.0.1:8000" in text:
        localhost_hits.append(entry.get("character_id"))
print(json.dumps({{"entry_count": len(entries), "localhost_hits": localhost_hits, "sample_urls": sample_urls}}, ensure_ascii=False))
"""
    return json.loads(_remote_python(config, script))


def _http_status(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return response.status, response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "")


def _remote_http_status(config: RepairConfig, url: str) -> tuple[int, str]:
    output = run_ssh(
        config,
        (
            "python3 - <<'PY'\n"
            "import sys, urllib.request, urllib.error\n"
            f"url = {url!r}\n"
            "request = urllib.request.Request(url, method='GET')\n"
            "try:\n"
            "    with urllib.request.urlopen(request, timeout=30.0) as response:\n"
            "        print(response.status)\n"
            "        print(response.headers.get('Content-Type', ''))\n"
            "except urllib.error.HTTPError as exc:\n"
            "    print(exc.code)\n"
            "    print(exc.headers.get('Content-Type', ''))\n"
            "PY"
        ),
    )
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"remote HTTP probe returned no output for {url}")
    status = int(lines[0])
    content_type = lines[1] if len(lines) > 1 else ""
    return status, content_type


def repair(config: RepairConfig) -> dict[str, Any]:
    if not config.local_portrait_dir.exists():
        raise RuntimeError(f"local portrait directory not found: {config.local_portrait_dir}")
    local_files = local_portrait_files(config.local_portrait_dir)
    if not local_files:
        raise RuntimeError(f"local portrait directory has no current.png files: {config.local_portrait_dir}")

    run_ssh(
        config,
        (
            f"mkdir -p {config.remote_roster_portrait_dir} "
            f"{config.remote_author_job_portrait_dir}"
        ),
    )
    run_rsync(config, config.local_portrait_dir, config.remote_roster_portrait_dir)
    backup_path = _backup_remote_runtime_catalog(config)
    rewritten_path = _rewrite_runtime_catalog(config)
    published_story_patch = _rewrite_published_story_portrait_urls(config)
    _deploy_nginx_config(config)
    _restart_backend(config)
    remote_files = _remote_file_count(config, config.remote_roster_portrait_dir)
    return {
        "local_portrait_count": len(local_files),
        "remote_portrait_count": remote_files,
        "runtime_catalog_backup": backup_path,
        "runtime_catalog_path": rewritten_path,
        "published_story_patch": published_story_patch,
    }


def verify(config: RepairConfig) -> dict[str, Any]:
    sample_local = local_portrait_files(config.local_portrait_dir)
    if not sample_local:
        raise RuntimeError(f"local portrait directory has no sample files: {config.local_portrait_dir}")
    sample_relative = sample_local[0].relative_to(config.local_portrait_dir)
    sample_url = f"{config.public_base_url}/portraits/roster/{sample_relative.as_posix()}"
    internal_url = "http://127.0.0.1:8010" + urllib.parse.urlparse(sample_url).path
    catalog_summary = _verify_catalog_base_url(config)
    internal_status, internal_content_type = _remote_http_status(config, internal_url)
    public_status, public_content_type = _http_status(sample_url)
    return {
        "remote_portrait_count": _remote_file_count(config, config.remote_roster_portrait_dir),
        "catalog_summary": catalog_summary,
        "internal_http": {
            "url": internal_url,
            "status": internal_status,
            "content_type": internal_content_type,
        },
        "public_http": {
            "url": sample_url,
            "status": public_status,
            "content_type": public_content_type,
        },
    }


def _request_json(
    method: str,
    url: str,
    *,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float,
) -> tuple[dict[str, Any], list[str]]:
    payload = None
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_headers = [f"{key}: {value}" for key, value in response.headers.items()]
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{method} {url} did not return a JSON object")
        return parsed, response_headers


def _cookie_header(response_headers: list[str]) -> str:
    cookies = []
    for header in response_headers:
        if not header.lower().startswith("set-cookie:"):
            continue
        cookie_value = header.split(":", 1)[1].strip().split(";", 1)[0]
        cookies.append(cookie_value)
    if not cookies:
        raise RuntimeError("authentication response did not set a session cookie")
    return "; ".join(cookies)


def _cookie_header_from_mapping(response_headers: dict[str, str]) -> str:
    for key, value in response_headers.items():
        if key.lower() == "set-cookie":
            return value.split(";", 1)[0]
    raise RuntimeError("authentication response did not set a session cookie")


def _story_row(config: RepairConfig, story_id: str) -> dict[str, Any]:
    story_library_path = _resolved_remote_story_library_path(config)
    script = f"""
import sqlite3, json
conn = sqlite3.connect({story_library_path!r})
cur = conn.cursor()
cur.execute("SELECT story_id, prompt_seed, visibility, owner_user_id, published_at FROM published_stories WHERE story_id = ?", ({story_id!r},))
row = cur.fetchone()
if row is None:
    raise SystemExit("story_not_found")
print(json.dumps({{"story_id": row[0], "prompt_seed": row[1], "visibility": row[2], "owner_user_id": row[3], "published_at": row[4]}}, ensure_ascii=False))
"""
    output = _remote_python(config, script).strip()
    if output == "story_not_found":
        raise RuntimeError(f"story_id not found on remote: {story_id}")
    return json.loads(output)


def _update_story_visibility_and_owner(config: RepairConfig, *, story_id: str, visibility: str, owner_user_id: str) -> None:
    story_library_path = _resolved_remote_story_library_path(config)
    script = f"""
import sqlite3
conn = sqlite3.connect({story_library_path!r})
cur = conn.cursor()
cur.execute(
    "UPDATE published_stories SET visibility = ?, owner_user_id = ? WHERE story_id = ?",
    ({visibility!r}, {owner_user_id!r}, {story_id!r}),
)
conn.commit()
print(cur.rowcount)
"""
    _remote_python(config, script)


def replace_story(config: RepairConfig, *, story_id: str, visibility: str, request_timeout_seconds: float, poll_timeout_seconds: float, poll_interval_seconds: float) -> dict[str, Any]:
    parsed_api = urllib.parse.urlparse(config.api_base_url)
    if parsed_api.hostname in {"127.0.0.1", "localhost"}:
        return _remote_replace_story(
            config,
            story_id=story_id,
            visibility=visibility,
            request_timeout_seconds=request_timeout_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    base_url = config.api_base_url
    existing_story = _story_row(config, story_id)
    auth_payload, auth_headers = _request_json(
        "POST",
        f"{base_url}/auth/register",
        data={
            "display_name": "Portrait Repair",
            "email": f"portrait-repair-{base64.urlsafe_b64encode(os.urandom(9)).decode('ascii').rstrip('=')}@bench.local",
            "password": "BenchPass123!",
        },
        timeout_seconds=request_timeout_seconds,
    )
    if not auth_payload.get("authenticated"):
        raise RuntimeError("auth registration did not return authenticated=true")
    cookie_header = _cookie_header(auth_headers)
    headers = {"Cookie": cookie_header}
    preview_payload, _ = _request_json(
        "POST",
        f"{base_url}/author/story-previews",
        data={"prompt_seed": existing_story["prompt_seed"]},
        headers=headers,
        timeout_seconds=request_timeout_seconds,
    )
    job_payload, _ = _request_json(
        "POST",
        f"{base_url}/author/jobs",
        data={"prompt_seed": existing_story["prompt_seed"], "preview_id": preview_payload["preview_id"]},
        headers=headers,
        timeout_seconds=request_timeout_seconds,
    )
    job_id = str(job_payload["job_id"])
    started_at = time.monotonic()
    while True:
        status_payload, _ = _request_json(
            "GET",
            f"{base_url}/author/jobs/{job_id}",
            headers=headers,
            timeout_seconds=request_timeout_seconds,
        )
        if status_payload.get("status") in {"completed", "failed"}:
            break
        if time.monotonic() - started_at > poll_timeout_seconds:
            raise RuntimeError(f"job {job_id} timed out waiting for completion")
        time.sleep(poll_interval_seconds)
    if status_payload.get("status") != "completed":
        raise RuntimeError(f"job {job_id} completed with status={status_payload.get('status')}")
    publish_payload, _ = _request_json(
        "POST",
        f"{base_url}/author/jobs/{job_id}/publish?visibility={visibility}",
        headers=headers,
        timeout_seconds=request_timeout_seconds,
    )
    new_story_id = str(publish_payload["story_id"])
    detail_payload, _ = _request_json(
        "GET",
        f"{base_url}/stories/{new_story_id}",
        headers=headers,
        timeout_seconds=request_timeout_seconds,
    )
    cast_manifest = dict(detail_payload.get("cast_manifest") or {})
    entries = list(cast_manifest.get("entries") or [])
    portrait_entries = [entry for entry in entries if entry.get("portrait_url")]
    if not portrait_entries:
        raise RuntimeError(f"replacement story {new_story_id} did not include portrait_url in cast_manifest")
    play_session_payload, _ = _request_json(
        "POST",
        f"{base_url}/play/sessions",
        data={"story_id": new_story_id},
        headers=headers,
        timeout_seconds=request_timeout_seconds,
    )
    play_portrait_hits: list[str] = []

    def _walk_play_payload(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "current_portrait_url" and isinstance(value, str) and value:
                    play_portrait_hits.append(value)
                _walk_play_payload(value)
            return
        if isinstance(obj, list):
            for item in obj:
                _walk_play_payload(item)

    _walk_play_payload(play_session_payload)
    _update_story_visibility_and_owner(
        config,
        story_id=new_story_id,
        visibility=str(existing_story["visibility"]),
        owner_user_id=str(existing_story["owner_user_id"]),
    )
    _update_story_visibility_and_owner(
        config,
        story_id=story_id,
        visibility="private",
        owner_user_id=str(existing_story["owner_user_id"]),
    )
    return {
        "old_story": existing_story,
        "job_id": job_id,
        "new_story_id": new_story_id,
        "portrait_entry_count": len(portrait_entries),
        "sample_portrait_urls": [entry["portrait_url"] for entry in portrait_entries[:3]],
        "play_portrait_hit_count": len(play_portrait_hits),
        "play_portrait_samples": play_portrait_hits[:3],
    }


def _remote_replace_story(
    config: RepairConfig,
    *,
    story_id: str,
    visibility: str,
    request_timeout_seconds: float,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    story_library_path = _resolved_remote_story_library_path(config)
    script = f"""
import json
import os
import secrets
import sqlite3
import time
import urllib.request
from pathlib import Path

BASE_URL = {config.api_base_url!r}
STORY_ID = {story_id!r}
VISIBILITY = {visibility!r}
REQUEST_TIMEOUT = {request_timeout_seconds!r}
POLL_TIMEOUT = {poll_timeout_seconds!r}
POLL_INTERVAL = {poll_interval_seconds!r}
DB_PATH = {story_library_path!r}

def request_json(method, url, *, data=None, headers=None):
    payload = None
    request_headers = {{"Content-Type": "application/json"}}
    if headers:
        request_headers.update(headers)
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        response_headers = dict(response.headers.items())
        parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{{method}} {{url}} did not return a JSON object")
        return parsed, response_headers

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT story_id, prompt_seed, visibility, owner_user_id, published_at FROM published_stories WHERE story_id = ?", (STORY_ID,))
row = cur.fetchone()
if row is None:
    raise SystemExit("story_not_found")
old_story = {{
    "story_id": row[0],
    "prompt_seed": row[1],
    "visibility": row[2],
    "owner_user_id": row[3],
    "published_at": row[4],
}}

auth_payload, auth_headers = request_json(
    "POST",
    f"{{BASE_URL}}/auth/register",
    data={{
        "display_name": "Portrait Repair",
        "email": f"portrait-repair-{{secrets.token_hex(6)}}@bench.local",
        "password": "BenchPass123!",
    }},
)
if not auth_payload.get("authenticated"):
    raise RuntimeError("auth registration did not return authenticated=true")
cookie_header = None
for key, value in auth_headers.items():
    if key.lower() == "set-cookie":
        cookie_header = value.split(";", 1)[0]
        break
if not cookie_header:
    raise RuntimeError("auth registration did not set a session cookie")
headers = {{"Cookie": cookie_header}}

preview_payload, _ = request_json(
    "POST",
    f"{{BASE_URL}}/author/story-previews",
    data={{"prompt_seed": old_story["prompt_seed"]}},
    headers=headers,
)
job_payload, _ = request_json(
    "POST",
    f"{{BASE_URL}}/author/jobs",
    data={{"prompt_seed": old_story["prompt_seed"], "preview_id": preview_payload["preview_id"]}},
    headers=headers,
)
job_id = str(job_payload["job_id"])
started_at = time.monotonic()
while True:
    status_payload, _ = request_json("GET", f"{{BASE_URL}}/author/jobs/{{job_id}}", headers=headers)
    if status_payload.get("status") in {{"completed", "failed"}}:
        break
    if time.monotonic() - started_at > POLL_TIMEOUT:
        raise RuntimeError(f"job {{job_id}} timed out")
    time.sleep(POLL_INTERVAL)
if status_payload.get("status") != "completed":
    raise RuntimeError(f"job {{job_id}} completed with status={{status_payload.get('status')}}")

publish_payload, _ = request_json(
    "POST",
    f"{{BASE_URL}}/author/jobs/{{job_id}}/publish?visibility={{VISIBILITY}}",
    headers=headers,
)
new_story_id = str(publish_payload["story_id"])
detail_payload, _ = request_json("GET", f"{{BASE_URL}}/stories/{{new_story_id}}", headers=headers)
entries = list(dict(detail_payload.get("cast_manifest") or {{}}).get("entries") or [])
portrait_entries = [entry for entry in entries if entry.get("portrait_url")]
if not portrait_entries:
    raise RuntimeError(f"replacement story {{new_story_id}} did not include portrait_url in cast_manifest")
play_session_payload, _ = request_json(
    "POST",
    f"{{BASE_URL}}/play/sessions",
    data={{"story_id": new_story_id}},
    headers=headers,
)
play_portrait_hits = []
def walk(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "current_portrait_url" and isinstance(value, str) and value:
                play_portrait_hits.append(value)
            walk(value)
    elif isinstance(obj, list):
        for item in obj:
            walk(item)
walk(play_session_payload)

cur.execute(
    "UPDATE published_stories SET visibility = ?, owner_user_id = ? WHERE story_id = ?",
    (old_story["visibility"], old_story["owner_user_id"], new_story_id),
)
cur.execute(
    "UPDATE published_stories SET visibility = ?, owner_user_id = ? WHERE story_id = ?",
    ("private", old_story["owner_user_id"], old_story["story_id"]),
)
conn.commit()
print(json.dumps({{
    "old_story": old_story,
    "job_id": job_id,
    "new_story_id": new_story_id,
    "portrait_entry_count": len(portrait_entries),
    "sample_portrait_urls": [entry["portrait_url"] for entry in portrait_entries[:3]],
    "play_portrait_hit_count": len(play_portrait_hits),
    "play_portrait_samples": play_portrait_hits[:3],
}}, ensure_ascii=False))
"""
    output = _remote_python(config, script).strip()
    if output == "story_not_found":
        raise RuntimeError(f"story_id not found on remote: {story_id}")
    return json.loads(output)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = _config_from_args(args)
    if args.command == "repair":
        payload = repair(config)
    elif args.command == "verify":
        payload = verify(config)
    elif args.command == "replace-story":
        payload = replace_story(
            config,
            story_id=str(args.story_id),
            visibility=str(args.visibility),
            request_timeout_seconds=float(args.request_timeout_seconds),
            poll_timeout_seconds=float(args.poll_timeout_seconds),
            poll_interval_seconds=float(args.poll_interval_seconds),
        )
    else:
        raise RuntimeError(f"unsupported command: {args.command}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
