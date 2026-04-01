"""
CleverSearch production security preflight checker.

Usage:
  python scripts/security_preflight.py

Checks the current environment variables and exits with non-zero code when
critical security requirements are not met.
"""

from __future__ import annotations

import os
import sys
from typing import List


WEAK_OS_PASSWORDS = {"admin", "admin123!", "changeme", "password", "123456"}
DEFAULT_JWT_SECRET = "change-this-in-production-at-least-32-chars"


def get_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def get_csv(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def main() -> int:
    env = os.getenv("APP_ENV", "dev").strip().lower()

    issues: List[str] = []
    warnings: List[str] = []

    cors_origins = get_csv("CORS_ALLOWED_ORIGINS", "")
    allowed_hosts = get_csv("ALLOWED_HOSTS", "")
    jwt_secret = os.getenv("JWT_SECRET", DEFAULT_JWT_SECRET)
    os_password = os.getenv("OS_PASSWORD", "")
    docs_enabled = get_bool("ENABLE_API_DOCS", "true")
    verify_certs = get_bool("OPENSEARCH_VERIFY_CERTS", "false")

    jwt_exp = int(os.getenv("JWT_EXPIRE_MINUTES", "30"))
    refresh_exp = int(os.getenv("JWT_REFRESH_EXPIRE_MINUTES", "1440"))

    if not cors_origins:
        issues.append("CORS_ALLOWED_ORIGINS is empty.")
    if "*" in cors_origins:
        issues.append("CORS_ALLOWED_ORIGINS must not contain '*'.")

    if not allowed_hosts:
        issues.append("ALLOWED_HOSTS is empty.")
    if "*" in allowed_hosts:
        issues.append("ALLOWED_HOSTS must not contain '*'.")

    if jwt_secret == DEFAULT_JWT_SECRET or len(jwt_secret) < 32:
        issues.append("JWT_SECRET must be replaced with a strong secret (>=32 chars).")

    if os_password.strip().lower() in WEAK_OS_PASSWORDS or len(os_password.strip()) < 10:
        issues.append("OS_PASSWORD is weak. Use a strong password with sufficient length/complexity.")

    if docs_enabled and env in {"prod", "production"}:
        issues.append("ENABLE_API_DOCS must be false in production.")

    if not verify_certs and env in {"prod", "production"}:
        issues.append("OPENSEARCH_VERIFY_CERTS must be true in production.")

    if jwt_exp > 60:
        warnings.append(f"JWT_EXPIRE_MINUTES={jwt_exp} is long; 30~60 is recommended.")

    if refresh_exp > 10080:
        warnings.append(
            f"JWT_REFRESH_EXPIRE_MINUTES={refresh_exp} is long; <=10080 (7 days) is recommended."
        )

    print("=== CleverSearch Security Preflight ===")
    print(f"APP_ENV: {env}")

    if warnings:
        print("\n[WARNINGS]")
        for w in warnings:
            print(f"- {w}")

    if issues:
        print("\n[FAIL]")
        for i in issues:
            print(f"- {i}")
        return 1

    print("\n[PASS] Security preflight checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
