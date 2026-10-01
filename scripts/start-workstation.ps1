param([switch]$Test, [switch]$CheckOnly)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
Set-Location $root
$file=if($Test){'.env.workstation-test'}else{'.env.workstation'}
$env:CLEVERSEARCH_ENV_FILE=Join-Path $root $file
$env:PYTHONUTF8='1'
if(-not (Test-Path $env:CLEVERSEARCH_ENV_FILE)){throw "Missing $file; see docs/LOCAL_SETUP_WORKLOG_20260930.md"}
& docker compose --env-file .env.workstation -f compose.workstation.yml up -d --wait
if($LASTEXITCODE -ne 0){throw 'Local database/search engine not ready'}
if($CheckOnly){exit 0}
if($Test){
    & .\.venv\Scripts\python.exe -m pytest tests -q
}else{
    & .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
}
exit $LASTEXITCODE