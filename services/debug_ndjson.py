from __future__ import annotations

import json
import os
import time
from typing import Any

_SESSION_ID = "15bc98"
# Debug-mode NDJSON sink (local workspace). Fails silently on hosts where path is absent.
_CURSOR_DEBUG_LOG = "/Users/enzoclement/coc-bot/.cursor/debug-15bc98.log"


def _ndjson_log_path() -> str | None:
    """Chemin NDJSON optionnel : premier non-vide parmi ces variables."""
    for key in ("AGENT_DEBUG_NDJSON_PATH", "AGENT_DEBUG_MAIN"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    return None


def debug_ndjson(
    *,
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict[str, Any] | None = None,
    run_id: str = "runtime",
) -> None:
    """Append a single NDJSON line for debug-mode evidence.

    Never include secrets/PII in `data`.
    """
    paths: list[str] = []
    env_path = _ndjson_log_path()
    if env_path:
        paths.append(env_path)
    paths.append(_CURSOR_DEBUG_LOG)
    # #region agent log
    payload = {
        "sessionId": _SESSION_ID,
        "timestamp": int(time.time() * 1000),
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "runId": run_id,
    }
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    for path in paths:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
    # #endregion
