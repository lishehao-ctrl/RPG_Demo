#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

import httpx

from benchmark_release import ToxiproxyManager, _default_toxiproxy_upstream


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage benchmark toxiproxy profiles.")
    parser.add_argument("profile", choices=["clean", "jitter_mild", "jitter_severe", "status"])
    parser.add_argument("--toxiproxy-url", default="http://127.0.0.1:8474")
    parser.add_argument("--proxy-name", default="llm_upstream")
    parser.add_argument("--listen", default="127.0.0.1:11452")
    parser.add_argument("--upstream", default=_default_toxiproxy_upstream())
    return parser.parse_args()


def _fetch_status(*, toxiproxy_url: str, proxy_name: str) -> dict:
    client = httpx.Client(timeout=10.0)
    try:
        resp = client.get(f"{toxiproxy_url.rstrip('/')}/proxies/{proxy_name}")
        if resp.status_code == 404:
            return {"exists": False, "proxy_name": proxy_name, "toxics": []}
        resp.raise_for_status()
        payload = resp.json() if isinstance(resp.json(), dict) else {}
        toxics = payload.get("toxics") if isinstance(payload, dict) else []
        return {
            "exists": True,
            "proxy_name": proxy_name,
            "listen": payload.get("listen"),
            "upstream": payload.get("upstream"),
            "toxics": toxics if isinstance(toxics, list) else [],
        }
    finally:
        client.close()


def main() -> None:
    args = _parse_args()
    manager = ToxiproxyManager(
        api_url=args.toxiproxy_url,
        proxy_name=args.proxy_name,
        listen=args.listen,
        upstream=args.upstream,
    )
    try:
        if args.profile == "status":
            print(json.dumps(_fetch_status(toxiproxy_url=args.toxiproxy_url, proxy_name=args.proxy_name), indent=2))
            return

        manager.apply_profile(args.profile)
        status = _fetch_status(toxiproxy_url=args.toxiproxy_url, proxy_name=args.proxy_name)
        print(json.dumps({"applied_profile": args.profile, "status": status}, indent=2))
    finally:
        manager.close()


if __name__ == "__main__":
    main()
