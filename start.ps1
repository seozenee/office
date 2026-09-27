# Personal AI Office — local one-command start (Windows PowerShell)
#   powershell -ExecutionPolicy Bypass -File start.ps1          install (first run) and start
#   powershell -ExecutionPolicy Bypass -File start.ps1 -Demo    use the offline research snapshot
param([switch]$Demo)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host "Python 3.11+ 가 필요합니다: https://www.python.org/downloads/"; exit 1 }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { Write-Host "Node.js 20+ 가 필요합니다: https://nodejs.org/"; exit 1 }

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  $secret = python -c "import secrets; print(secrets.token_urlsafe(32))"
  $pass = python -c "import secrets; print(secrets.token_urlsafe(9))"
  (Get-Content .env) -replace '^SECRET_KEY=.*$', "SECRET_KEY=$secret" -replace '^ADMIN_PASSWORD=.*$', "ADMIN_PASSWORD=$pass" | Set-Content .env -Encoding utf8
  Write-Host "✅ .env 생성 — 로그인: ceo / $pass  (나중에 .env 에서 변경 가능)"
}

if (-not (Test-Path backend\.venv)) {
  Write-Host "📦 백엔드 설치 중…"
  python -m venv backend\.venv
  backend\.venv\Scripts\python -m pip install -q --upgrade pip
  backend\.venv\Scripts\pip install -q -r backend\requirements.txt
  try { backend\.venv\Scripts\python -m playwright install chromium } catch { Write-Host "⚠️ 브라우저 에이전트용 Chromium 설치 실패 (다른 기능은 정상)" }
}
if (-not (Test-Path frontend\node_modules)) {
  Write-Host "📦 프런트엔드 설치 중…"
  Push-Location frontend; npm ci --no-audit --no-fund; Pop-Location
}

if ($Demo -and -not (Select-String -Path .env -Pattern '^FIXTURE_SEARCH_FILE=.' -Quiet)) {
  $corpus = Join-Path $PSScriptRoot "backend\data\demo_corpus"
  backend\.venv\Scripts\python backend\tests\fixtures\build_corpus.py $corpus | Out-Null
  (Get-Content .env) -replace '^SEARCH_PROVIDER=auto$', 'SEARCH_PROVIDER=fixture' | Set-Content .env -Encoding utf8
  Add-Content .env "FIXTURE_SEARCH_FILE=$corpus\search.json"
  Add-Content .env "FETCH_MIRROR_DIR=$corpus"
  Write-Host "✅ 데모 리서치 스냅샷 사용"
}

# load .env into this process for the backend
Get-Content .env | Where-Object { $_ -match '^[A-Z_]+=.+' } | ForEach-Object {
  $k, $v = $_ -split '=', 2; [Environment]::SetEnvironmentVariable($k, $v, "Process")
}
$api = Start-Process -PassThru -NoNewWindow -WorkingDirectory backend -FilePath (Join-Path $PSScriptRoot "backend\.venv\Scripts\python.exe") -ArgumentList "-m uvicorn app.main:app --port 8000"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
$web = Start-Process -PassThru -NoNewWindow -WorkingDirectory frontend -FilePath npm.cmd -ArgumentList "run dev"
Start-Sleep 8
Write-Host "`n🏢 Personal AI Office → http://localhost:3000   (API 문서: http://localhost:8000/docs)   종료: 이 창에서 Enter"
Start-Process "http://localhost:3000"
Read-Host | Out-Null
Stop-Process -Id $api.Id, $web.Id -Force -ErrorAction SilentlyContinue
