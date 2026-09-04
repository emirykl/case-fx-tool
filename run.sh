#!/usr/bin/env bash
# Starts the service. It must listen on $PORT (default 8080) and read the
# upstream base URL from $FX_UPSTREAM_BASE — we point that at a fake upstream
# when we review your work, so nothing here may hardcode frankfurter.dev.
set -euo pipefail
PORT="${PORT:-8080}"
exec python3 -m uvicorn fx_tool.app:app --host 0.0.0.0 --port "$PORT"
