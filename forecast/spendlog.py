"""Key resolution and OpenRouter usage reads. Never prints or logs key material."""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

KEY_SERVICE = "com.personal.openrouter-spend"
KEY_ACCOUNT = "openrouter-api-key"
ANALYTICS_SERVICE = "com.personal.openrouter-spend.analytics"
HERMES_ENV = pathlib.Path.home() / ".hermes" / ".env"
APP_SUPPORT = pathlib.Path.home() / "Library" / "Application Support" / "AI-Spending"
KEY_URL = "https://openrouter.ai/api/v1/key"
ANALYTICS_URL = "https://openrouter.ai/api/v1/analytics/query"


class NoKey(RuntimeError):
    pass


def _keychain(service: str, account: str) -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    value = out.stdout.strip()
    return value or None


def _dotenv(path: pathlib.Path, name: str) -> str | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(rf'\s*(?:export\s+)?{name}\s*=\s*["\']?([^"\'\s]+)', line)
        if m:
            return m.group(1)
    return None


def inference_key() -> str:
    """App Keychain -> environment -> Hermes .env. Raises NoKey."""
    key = (
        _keychain(KEY_SERVICE, KEY_ACCOUNT)
        or os.environ.get("OPENROUTER_API_KEY")
        or _dotenv(HERMES_ENV, "OPENROUTER_API_KEY")
    )
    if not key:
        raise NoKey("no OpenRouter inference key found")
    return key


def analytics_key() -> str:
    """Account-scoped management key. Only needed for backfill."""
    key = (
        _keychain(ANALYTICS_SERVICE, "management-key")
        or os.environ.get("OPENROUTER_MANAGEMENT_KEY")
        or _dotenv(HERMES_ENV, "OPENROUTER_MANAGEMENT_KEY")
    )
    if not key:
        raise NoKey(
            "no management key: create one at openrouter.ai/settings/management-keys and store it as "
            f"Keychain item service={ANALYTICS_SERVICE!r} account='management-key'"
        )
    return key


def _request(url: str, key: str, payload: dict | None = None, timeout: int = 25) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def key_usage(key: str) -> dict:
    """usage_daily/weekly/monthly for this key (UTC windows). Rejects management keys."""
    body = _request(KEY_URL, key)["data"]
    if body.get("is_management_key") or body.get("is_provisioning_key"):
        raise RuntimeError("management key supplied where an inference key is required")
    out = {}
    for field in ("usage_daily", "usage_weekly", "usage_monthly"):
        value = body.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            out[field] = float(value)
    out["is_free_tier"] = bool(body.get("is_free_tier"))
    out["limit_remaining"] = body.get("limit_remaining")
    return out


def analytics_daily(key: str, start: str, end: str) -> list[dict]:
    """Daily total_usage rows. start/end are ISO-8601 UTC timestamps."""
    payload = {
        "metrics": ["total_usage", "request_count"],
        "dimensions": [],
        "granularity": "day",
        "time_range": {"start": start, "end": end},
    }
    try:
        body = _request(ANALYTICS_URL, key, payload)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError(
                "analytics rejected this key (403): a management key is required; "
                "regular inference keys cannot read historical analytics"
            ) from exc
        raise
    rows = body.get("data", {}).get("data", [])
    out = []
    for row in rows:
        day = row.get("date__day") or row.get("created_at__day")
        if not day:
            continue
        out.append({
            "day": str(day)[:10],
            "usage": float(row.get("total_usage") or 0.0),
            "requests": int(float(row.get("request_count") or 0)),
        })
    return out
