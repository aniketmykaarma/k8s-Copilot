"""Audit logging for K8sCopilot.

Every tool execution is appended to a JSONL audit log. Each line is a JSON object:

    {
      "ts": "2026-05-17T14:30:00Z",
      "session_id": "abc123",
      "user_query": "show me failing pods",
      "tool": "kubectl_get_pods",
      "params": {"namespace": "orders"},
      "outcome": "success" | "error" | "denied",
      "duration_ms": 142,
      "error": "<message if any>"
    }

This is intentionally append-only and structured for downstream parsing (jq, Splunk, etc).
"""

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class AuditLogger:
    """Append-only JSONL audit log for tool executions."""

    def __init__(self, log_path: Path):
        self.log_path = Path(log_path).expanduser()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_id = uuid.uuid4().hex[:8]

    def log(
        self,
        user_query: str,
        tool: str,
        params: Dict[str, Any],
        outcome: str,
        duration_ms: int,
        error: Optional[str] = None,
    ) -> None:
        """Append a single audit event."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "user_query": user_query,
            "tool": tool,
            "params": params,
            "outcome": outcome,
            "duration_ms": duration_ms,
        }
        if error:
            entry["error"] = error

        try:
            with open(self.log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            # Never fail an operation because audit logging failed.
            # In a production deployment you'd add a dead-letter fallback here.
            pass


class Timer:
    """Lightweight context manager to measure block duration."""

    def __init__(self):
        self.duration_ms: int = 0
        self._start: float = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.duration_ms = int((time.perf_counter() - self._start) * 1000)
