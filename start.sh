#!/usr/bin/env bash
# Personal AI Office — local one-command start (macOS / Linux)
#   ./start.sh          install (first run) and start backend :8000 + frontend :3000
#   ./start.sh --demo   also use the offline research snapshot (no search API key needed)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

command -v python3 >/dev/null || { echo "Python 3.11+ 가 필요합니다: https://www.python.org/downloads/"; exit 1; }
command -v npm >/dev/null || { echo "Node.js 20+ 가 필요합니다: https://nodejs.org/"; exit 1; }

if [ ! -f .env ]; then
  cp .env.example .env
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  PASS=$(python3 -c "import secrets; print(secrets.token_urlsafe(9))")
  python3 - "$SECRET" "$PASS" <<'PY'
import sys, re
s = open(".env").read()
s = re.sub(r"^SECRET_KEY=.*$", f"SECRET_KEY={sys.argv[1]}", s, flags=re.M)
s = re.sub(r"^ADMIN_PASSWORD=.*$", f"ADMIN_PASSWORD={sys.argv[2]}", s, flags=re.M)
open(".env", "w").write(s)
PY
  echo "✅ .env 생성 — 로그인: ceo / $PASS  (나중에 .env 에서 변경 가능)"
fi

if [ ! -d backend/.venv ]; then
  echo "📦 백엔드 설치 중…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --upgrade pip
  backend/.venv/bin/pip install -q -r backend/requirements.txt
  backend/.venv/bin/python -m playwright install chromium || echo "⚠️ 브라우저 에이전트용 Chromium 설치 실패 (다른 기능은 정상)"
fi
if [ ! -d frontend/node_modules ]; then
  echo "📦 프런트엔드 설치 중…"
  (cd frontend && npm ci --no-audit --no-fund)
fi

if [ "${1:-}" = "--demo" ] && ! grep -q "^FIXTURE_SEARCH_FILE=." .env; then
  (cd backend && PYTHON=.venv/bin/python ./scripts/demo_snapshot.sh "$ROOT/backend/data/demo_corpus" | grep -v "^#" >> ../.env)
  sed -i.bak 's/^SEARCH_PROVIDER=auto$/SEARCH_PROVIDER=fixture/' .env && rm -f .env.bak
  echo "✅ 데모 리서치 스냅샷 사용"
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd backend && set -a && . ../.env && set +a && .venv/bin/uvicorn app.main:app --port 8000) &
(cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev) &
sleep 6
echo ""
echo "🏢 Personal AI Office →  http://localhost:3000   (API 문서: http://localhost:8000/docs)"
echo "   종료: Ctrl+C"
( command -v open >/dev/null && open http://localhost:3000 ) || ( command -v xdg-open >/dev/null && xdg-open http://localhost:3000 ) || true
wait
