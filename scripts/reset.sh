#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"

docker compose up -d --wait
exec "$PYTHON" -m src.cli reset "$@"
