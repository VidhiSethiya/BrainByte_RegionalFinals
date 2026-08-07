"""Probe OPENAI_BASE_URL + OPENAI_API_KEY and list available models.

Reads backend/.env by default (never prints the full key).

Usage:
  python check_llm_endpoint.py
  python check_llm_endpoint.py --env backend/.env
  python check_llm_endpoint.py --base https://genailab.tcs.in/v1 --key sk-...
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_ENV = ROOT / "backend" / ".env"


def load_dotenv(path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    if not path.is_file():
        return vals
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def mask_key(key: str) -> str:
    if not key:
        return "<empty>"
    if len(key) <= 10:
        return key[:3] + "..."
    return f"{key[:7]}...{key[-4:]} (len={len(key)})"


def http_json(
    method: str,
    url: str,
    *,
    api_key: str,
    body: dict | None = None,
    timeout: float = 30,
    insecure: bool = True,
) -> tuple[int, dict | list | str]:
    data = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or ""
        try:
            payload = json.loads(raw) if raw else {"error": raw}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc)}


def normalize_base(base: str) -> str:
    return base.rstrip("/")


def candidate_bases(base: str) -> list[str]:
    """Try both root and /v1 — gateways differ on which is correct."""
    b = normalize_base(base)
    out = [b]
    if not b.endswith("/v1"):
        out.append(f"{b}/v1")
    return out


def extract_model_ids(payload: dict | list | str) -> list[str]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("data") or payload.get("models") or []
        if isinstance(items, dict):
            items = list(items.values())
    else:
        return []

    ids: list[str] = []
    for item in items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            mid = item.get("id") or item.get("model") or item.get("name")
            if mid:
                ids.append(str(mid))
    return sorted(set(ids), key=str.lower)


def main() -> int:
    parser = argparse.ArgumentParser(description="Test LLM API key and list models")
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="Path to .env")
    parser.add_argument("--base", default="", help="Override OPENAI_BASE_URL")
    parser.add_argument("--key", default="", help="Override OPENAI_API_KEY")
    parser.add_argument("--no-ping", action="store_true", help="Skip chat ping")
    args = parser.parse_args()

    env = load_dotenv(Path(args.env))
    base = normalize_base(args.base or env.get("OPENAI_BASE_URL", ""))
    key = args.key or env.get("OPENAI_API_KEY", "")
    configured = {
        "LLM_MODEL": env.get("LLM_MODEL", ""),
        "FAST_LLM_MODEL": env.get("FAST_LLM_MODEL", ""),
        "REASONING_MODEL": env.get("REASONING_MODEL", ""),
        "EMBEDDING_MODEL": env.get("EMBEDDING_MODEL", ""),
        "VISION_MODEL": env.get("VISION_MODEL", ""),
    }

    print("LLM endpoint check")
    print(f"  env file   : {args.env}")
    print(f"  base URL   : {base or '<missing>'}")
    print(f"  api key    : {mask_key(key)}")
    print(f"  provider   : {env.get('LLM_PROVIDER', '<unset>')}")
    print()

    if not base or not key:
        print("FAIL: OPENAI_BASE_URL and OPENAI_API_KEY are required.")
        return 1

    # 1) List models — try base and base/v1
    model_ids: list[str] = []
    working_base = base
    status = 0
    payload: dict | list | str = {}

    print("[1] List models")
    for cand in candidate_bases(base):
        models_url = f"{cand}/models"
        print(f"  Trying GET {models_url}")
        status, payload = http_json("GET", models_url, api_key=key, timeout=45)
        if status == 200:
            working_base = cand
            print(f"  PASS HTTP {status} via {cand}")
            model_ids = extract_model_ids(payload)
            if not model_ids:
                print("  WARN: 200 OK but no model ids parsed. Raw payload:")
                print(json.dumps(payload, indent=2)[:2000])
            else:
                print(f"  Found {len(model_ids)} model(s):")
                for mid in model_ids:
                    print(f"    - {mid}")
            break
        print(f"  FAIL HTTP {status}")
        print(f"  {json.dumps(payload, indent=2)[:800]}")
    else:
        print("  No working /models endpoint found.")

    print()

    # 2) Compare configured ids vs catalogue
    print("[2] Configured models vs catalogue")
    if not model_ids:
        print("  SKIP (no catalogue from /models)")
    else:
        catalogue = {m.lower(): m for m in model_ids}
        for label, mid in configured.items():
            if not mid:
                print(f"  {label}: <empty>")
                continue
            hit = catalogue.get(mid.lower())
            # also try without azure/ / azure_ai/ prefixes
            alt = mid.split("/", 1)[-1].lower()
            hit = hit or next((v for k, v in catalogue.items() if k.endswith(alt) or alt in k), None)
            if hit:
                print(f"  OK   {label}={mid}  (matched {hit})")
            else:
                print(f"  MISS {label}={mid}  (not found in /models list)")

    print()

    # 3) Auth ping via chat completions (uses FAST or LLM model)
    if args.no_ping:
        print("[3] Chat ping skipped (--no-ping)")
        return 0 if model_ids else 1

    ping_model = configured.get("FAST_LLM_MODEL") or configured.get("LLM_MODEL") or (model_ids[0] if model_ids else "")
    chat_url = f"{working_base}/chat/completions"
    print(f"[3] POST {chat_url}")
    print(f"  model={ping_model or '<none>'}")
    if not ping_model:
        print("  FAIL: no model id available to ping")
        return 1

    ping_status, ping_payload = http_json(
        "POST",
        chat_url,
        api_key=key,
        body={
            "model": ping_model,
            "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
            "max_tokens": 16,
            "temperature": 0,
        },
        timeout=60,
    )
    if ping_status == 200:
        # try to show assistant text
        text = ""
        if isinstance(ping_payload, dict):
            choices = ping_payload.get("choices") or []
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                text = (msg.get("content") or "").strip()
        print(f"  PASS HTTP {ping_status}")
        if text:
            print(f"  reply: {text[:200]}")
        return 0

    print(f"  FAIL HTTP {ping_status}")
    print(f"  {json.dumps(ping_payload, indent=2)[:1500]}")
    print()
    print("Hint: if /models works but chat fails, the key may be read-only or the model id is wrong.")
    print("Hint: OpenAI-compatible gateways usually need base URL ending in /v1")
    return 1


if __name__ == "__main__":
    sys.exit(main())
