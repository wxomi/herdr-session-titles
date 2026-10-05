#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"

PYTHON="$(command -v python3 2>/dev/null || echo "python3")"

exec "$PYTHON" -m session_titles "$@"
