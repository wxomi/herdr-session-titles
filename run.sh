#!/usr/bin/env bash
export PYTHONPATH="/Users/wxomi/.local/share/herdr-session-titles:${PYTHONPATH:-}"
exec /opt/homebrew/bin/python3 -m session_titles "$@"
