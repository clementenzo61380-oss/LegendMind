from __future__ import annotations

import json
import time
from typing import Any

_DEBUG_LOG_PATH = "/Users/enzoclement/coc-bot/.cursor/debug-15bc98.log"
_SESSION_ID = "15bc98"


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
    # #region agent log
    try:
        payload = {
            "sessionId": _SESSION_ID,
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "runId": run_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # #endregion

