#!/usr/bin/env bash
# Fetch the pinned base checkout; prints its path on stdout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/fetch_base.py" "$@"
