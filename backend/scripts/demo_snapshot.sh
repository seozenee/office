#!/usr/bin/env bash
# Build the offline research snapshot (search index + mirrored originals) and print the env vars
# that make the office research against it. Useful for demos without search API keys.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HERE/data/demo_corpus}"
"${PYTHON:-python3}" "$HERE/tests/fixtures/build_corpus.py" "$OUT" >/dev/null
cat <<ENV
# add these to .env (or export them) to run the office on the demo snapshot:
SEARCH_PROVIDER=fixture
FIXTURE_SEARCH_FILE=$OUT/search.json
FETCH_MIRROR_DIR=$OUT
ENV
