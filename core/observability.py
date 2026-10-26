"""Lightweight structured (JSON-lines) logging keyed by request ID.

Chosen over a heavyweight tracing stack (OpenTelemetry/Prometheus) deliberately: for a single-node
research deployment, JSON logs to a file + the per-request timings already captured in the TrustReport
give full traceability without extra services. Each request emits one structured audit line.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_CONFIGURED = False


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
        }
        if hasattr(record, "extra_fields"):
            payload.update(record.extra_fields)  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", log_file: str | Path | None = None, json_console: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("trustguard")
    root.setLevel(level)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(JsonLineFormatter() if json_console
                         else logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(JsonLineFormatter())
        root.addHandler(fh)
    root.propagate = False
    _CONFIGURED = True


def audit(logger: logging.Logger, msg: str, **fields) -> None:
    """Emit a structured audit record. Sensitive content (question text, drafts) is never logged here;
    only identifiers, decisions, counts and timings."""
    logger.info(msg, extra={"extra_fields": fields})
