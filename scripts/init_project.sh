#!/usr/bin/env bash
# Compatibility entry point; Python handles canonical paths and checked subprocesses.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/init_project.py" "$@"
