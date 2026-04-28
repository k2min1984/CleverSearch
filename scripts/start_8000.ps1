param(
    [string]$EnvFile = ".env.example",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$UseSsl,
    [switch]$UseReload,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptDir ".."))
$stopScript = Join-Path $scriptDir "stop_8000.ps1"
$startDev = Join-Path $scriptDir "start_dev.ps1"

# 사용자가 기본값을 그대로 쓰는 경우, .env.yatap이 있으면 우선 사용
if ((-not $PSBoundParameters.ContainsKey("EnvFile")) -and $EnvFile -eq ".env.example") {
    $yatapEnv = Join-Path $repoRoot ".env.yatap"
    if (Test-Path $yatapEnv) {
        $EnvFile = ".env.yatap"
    }
}

Write-Host "[RUN][8000] 종료 정리 먼저 수행"
& pwsh -File $stopScript -Port $Port
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[RUN][8000] stop_8000.ps1 실패(계속 진행): 포트 잔존 점유일 수 있습니다. 재시도 시작합니다."
}

$scriptArgs = @(
    "-EnvFile", $EnvFile,
    "-BindHost", $BindHost,
    "-Port", "$Port",
    "-KillExisting",
    "-NoAutoPortFallback"
)

if ($UseSsl) { $scriptArgs += "-UseSsl" }
if (-not $UseReload) { $scriptArgs += "-NoReload" }
if ($CheckOnly) { $scriptArgs += "-CheckOnly" }

Write-Host "[RUN][8000] 시작 명령 위임: start_dev.ps1"
& pwsh -File $startDev @scriptArgs
if ($LASTEXITCODE -eq 0) {
    exit 0
}

Write-Warning "[RUN][8000] start_dev.ps1 비정상 종료 코드: $LASTEXITCODE"

# 이미 8000에서 서비스가 살아있는 경우(권한 문제로 기존 프로세스 종료 실패 등)는 성공으로 간주
Start-Sleep -Milliseconds 800
try {
    $health = Invoke-WebRequest -Uri ("http://{0}:{1}/" -f $BindHost, $Port) -UseBasicParsing -TimeoutSec 3
    if ($health.StatusCode -ge 200 -and $health.StatusCode -lt 500) {
        Write-Host "[RUN][8000] 기존 서비스가 이미 실행 중으로 확인되어 성공 처리합니다."
        exit 0
    }
}
catch {
    # no-op: 실제 실패로 처리
}

exit $LASTEXITCODE
