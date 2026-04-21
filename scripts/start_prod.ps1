param(
    [string]$EnvFile = ".env.production",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8443,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

function Get-PythonCommand {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    throw "Python 실행 파일을 찾을 수 없습니다. Python 3.10+ 설치 후 다시 시도하세요."
}

function Ensure-VenvAndDependencies {
    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $reqPath = Join-Path $repoRoot "requirements.txt"

    if (-not (Test-Path $venvPy)) {
        $pyCmd = Get-PythonCommand
        Write-Host "[RUN][PROD] .venv 없음 -> 가상환경 생성"
        & $pyCmd[0] @($pyCmd[1..($pyCmd.Length-1)] + @("-m", "venv", ".venv"))
        if ($LASTEXITCODE -ne 0) {
            throw "가상환경 생성 실패"
        }
    }

    Write-Host "[RUN][PROD] 패키지 설치/업데이트"
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip 업그레이드 실패"
    }
    if (Test-Path $reqPath) {
        & $venvPy -m pip install -r $reqPath
        if ($LASTEXITCODE -ne 0) {
            throw "requirements 설치 실패"
        }
    } else {
        throw "requirements.txt를 찾을 수 없습니다: $reqPath"
    }
}

function Import-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        throw "운영 env 파일을 찾을 수 없습니다: $Path"
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $pair = $line -split "=", 2
        if ($pair.Count -ne 2) { return }
        $key = $pair[0].Trim()
        $value = $pair[1].Trim()
        [System.Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

Write-Host "[RUN][PROD] env 파일 로드: $EnvFile"
if (-not (Test-Path $EnvFile) -and (Test-Path ".env.production.example")) {
    Write-Host "[RUN][PROD] $EnvFile 없음 -> .env.production.example 사용"
    $EnvFile = ".env.production.example"
}
Import-EnvFile -Path $EnvFile
Ensure-VenvAndDependencies

# 운영 모드는 production 강제
$env:APP_ENV = "production"
$env:ENABLE_API_DOCS = "false"

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$py = [System.IO.Path]::GetFullPath($py)
if (-not (Test-Path $py)) {
    throw "가상환경 파이썬을 찾을 수 없습니다: $py"
}

Write-Host "[RUN][PROD] security preflight 실행"
& $py "scripts/security_preflight.py"
if ($LASTEXITCODE -ne 0) {
    throw "security_preflight 실패로 기동 중단"
}

$args = @(
    "-m", "uvicorn", "app.main:app",
    "--host", $BindHost,
    "--port", "$Port"
)

Write-Host "[RUN][PROD] command: $py $($args -join ' ')"
if ($CheckOnly) {
    Write-Host "[RUN][PROD] CheckOnly 모드 완료"
    exit 0
}

& $py @args
