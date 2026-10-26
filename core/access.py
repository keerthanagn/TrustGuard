"""Lightweight access control for admin surfaces (Knowledge Base management, full audit drafts).

This is a pragmatic gate for a single-node research prototype, NOT a substitute for real authentication
in a multi-user deployment. The admin token is read from the environment (TRUSTGUARD_ADMIN_TOKEN) and
compared in constant time. Behaviour:

  - token set in env            -> admin surfaces require the matching token
  - no token, require_admin_token=false -> open locally (single-user mode)
  - no token, require_admin_token=true  -> admin surfaces are LOCKED (fail closed) until a token is set
"""
from __future__ import annotations

import hmac
import os

ENV_VAR = "TRUSTGUARD_ADMIN_TOKEN"


def admin_token() -> str:
    return os.environ.get(ENV_VAR, "")


def admin_required(settings) -> bool:
    """Whether an admin token must be supplied to access admin surfaces."""
    return bool(admin_token()) or bool(settings.raw.get("security", {}).get("require_admin_token", False))


def check_admin(settings, provided: str | None) -> tuple[bool, str]:
    """Return (allowed, reason)."""
    token = admin_token()
    if token:
        if provided and hmac.compare_digest(provided, token):
            return True, "authenticated"
        return False, "An admin token is required for this action."
    if settings.raw.get("security", {}).get("require_admin_token", False):
        return False, (f"Admin surfaces are locked: set the {ENV_VAR} environment variable to enable them.")
    return True, "single-user mode (no admin token configured)"
