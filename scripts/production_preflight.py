"""Validate deployment secrets without printing them. No services are started."""
from __future__ import annotations
import argparse
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

SECRETS = ("POSTGRES_PASSWORD", "RUNTIME_DB_PASSWORD", "API_TOKEN", "SESSION_SECRET", "APP_ACCESS_PASSWORD")

def deployment_values(path: Path, environment=None) -> dict[str, str]:
    values = read_env(path)
    environment = os.environ if environment is None else environment
    # Compose gives shell variables precedence over --env-file, even when empty.
    for key in (*SECRETS, "APP_PUBLIC_ORIGIN", "FRONTEND_PORT"):
        if key in environment:
            values[key] = environment[key]
    return values

def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key.strip() in values:
            raise ValueError("invalid or duplicate environment key")
        values[key.strip()] = value.strip().strip('"\'')
    return values

def validate(values: dict[str, str]) -> list[str]:
    errors = []
    for key in SECRETS:
        value = values.get(key, "")
        if len(value) < 32 or re.search(r"replace|example|change.?me|demo", value, re.I):
            errors.append(f"{key}: requires an independent random secret of at least 32 characters")
    if len({values.get(key) for key in SECRETS}) != len(SECRETS):
        errors.append("Secrets must be different")
    for key in ("POSTGRES_PASSWORD", "RUNTIME_DB_PASSWORD"):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{32,}", values.get(key, "")):
            errors.append(f"{key}: use URL-safe generated characters")
    origin = urlsplit(values.get("APP_PUBLIC_ORIGIN", ""))
    if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
        errors.append("APP_PUBLIC_ORIGIN: canonical HTTPS origin required (without trailing slash)")
    try:
        if not 1024 <= int(values.get("FRONTEND_PORT", "53002")) <= 65535:
            raise ValueError()
    except ValueError:
        errors.append("FRONTEND_PORT: invalid non-privileged port")
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    args = parser.parse_args()
    try:
        errors = validate(deployment_values(args.env_file))
    except (ValueError, OSError):
        errors = ["Could not read a valid deployment env file"]
    if errors:
        print("\n".join(errors))
        raise SystemExit(1)
    print("Configuration checks passed. Scope: private single-tenant deployment; not multi-user production acceptance.")

if __name__ == "__main__":
    main()
