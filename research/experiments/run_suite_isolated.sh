#!/usr/bin/env bash
# Full test suite in an isolated mirror of the working tree (R5).
#
# config/settings.py lets .env override OS environment variables, so environment overrides alone cannot stop a
# test from reading live credentials. The mirror holds only tracked and new (non-ignored) files, so .env,
# models/ and every other git-ignored file are absent and nothing in the suite can reach a live service.
#
# Usage: research/experiments/run_suite_isolated.sh <output-log>     (run from the repo root)
set -euo pipefail
OUT="${1:?usage: run_suite_isolated.sh <output-log>}"
PY="${MAPNAI_PY:-$HOME/.venvs/mapnai-research/Scripts/python.exe}"
MIRROR="${MAPNAI_SUITE_MIRROR:-${TMPDIR:-/tmp}/mapnai_suite_mirror}"

rm -rf "$MIRROR" && mkdir -p "$MIRROR"
git ls-files -z -co --exclude-standard | while IFS= read -r -d '' f; do
  [ -f "$f" ] || continue                                  # deleted but still tracked
  mkdir -p "$MIRROR/$(dirname "$f")" && cp "$f" "$MIRROR/$f"
done
if [ -e "$MIRROR/.env" ]; then echo "refusing: .env found in the mirror" >&2; exit 2; fi

cd "$MIRROR"
GROQ_API_KEY="" OPENAI_API_KEY="" PYTHONDONTWRITEBYTECODE=1 \
  "$PY" -m pytest -p no:cacheprovider -rfEs > "$OUT" 2>&1 || true
tail -1 "$OUT"
