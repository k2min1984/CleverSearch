param(
    [string]$EnvFile = ".env.example",
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$UseSsl,
    [string]$SslKeyFile = "cert/localhost+2-key.pem",
    [string]$SslCertFile = "cert/localhost+2.pem",
    [switch]$KillExisting = $true,
    [switch]$NoAutoPortFallback,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"

# 사용자가 EnvFile을 명시하지 않은 경우에만, 원격 DB 전용 파일을 우선 사용
if ((-not $PSBoundParameters.ContainsKey("EnvFile")) -and $EnvFile -eq ".env.example") {
    $repoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $yatapEnv = Join-Path $repoRoot ".env.yatap"
    if (Test-Path $yatapEnv) {
        $EnvFile = ".env.yatap"
    }
}

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
        Write-Host "[RUN][DEV] .venv 없음 -> 가상환경 생성"
        & $pyCmd[0] @($pyCmd[1..($pyCmd.Length - 1)] + @("-m", "venv", ".venv"))
        if ($LASTEXITCODE -ne 0) {
            throw "가상환경 생성 실패"
        }
    }

    Write-Host "[RUN][DEV] 패키지 설치/업데이트"
    & $venvPy -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip 업그레이드 실패"
    }
    if (Test-Path $reqPath) {
        & $venvPy -m pip install -r $reqPath
        if ($LASTEXITCODE -ne 0) {
            throw "requirements 설치 실패"
        }
    }
    else {
        throw "requirements.txt를 찾을 수 없습니다: $reqPath"
    }
}

function Resolve-AbsolutePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\$Path"))
}

function Stop-UvicornPythonProcesses {
    $targets = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn\s+app\.main:app' } |
    Select-Object -ExpandProperty ProcessId -Unique

    if ($targets) {
        foreach ($procId in $targets) {
            try { Stop-Process -Id $procId -Force -ErrorAction Stop } catch {}
        }
        Write-Host "[RUN][DEV] 기존 uvicorn 프로세스 종료: $($targets -join ',')"
    }
}

function Test-PortBindable {
    param(
        [Parameter(Mandatory = $true)][string]$BindAddress,
        [Parameter(Mandatory = $true)][int]$PortNumber
    )

    $socket = $null
    try {
        $ip = [System.Net.IPAddress]::Parse($BindAddress)
        $socket = New-Object System.Net.Sockets.Socket([System.Net.Sockets.AddressFamily]::InterNetwork, [System.Net.Sockets.SocketType]::Stream, [System.Net.Sockets.ProtocolType]::Tcp)
        $socket.ExclusiveAddressUse = $true
        $socket.Bind((New-Object System.Net.IPEndPoint($ip, $PortNumber)))
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($socket) { $socket.Dispose() }
    }
}

function Get-AvailablePort {
    param(
        [Parameter(Mandatory = $true)][string]$BindAddress,
        [Parameter(Mandatory = $true)][int]$PreferredPort,
        [int]$MaxAttempts = 20
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        $candidate = $PreferredPort + $i
        if (Test-PortBindable -BindAddress $BindAddress -PortNumber $candidate) {
            return $candidate
        }
    }

    throw "사용 가능한 포트를 찾지 못했습니다. 시작 포트=$PreferredPort"
}

function Import-EnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Env 파일을 찾을 수 없습니다: $Path"
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

Write-Host "[RUN][DEV] env 파일 로드: $EnvFile"
Import-EnvFile -Path $EnvFile
Ensure-VenvAndDependencies

# 개발 기본값: 빠른 반복을 위해 HTTP + reload 사용
if (-not $env:APP_ENV) { $env:APP_ENV = "dev" }
if (-not $env:ENABLE_API_DOCS) { $env:ENABLE_API_DOCS = "true" }
$env:WATCHFILES_FORCE_POLLING = "true"

if ($KillExisting) {
    Stop-UvicornPythonProcesses
}

$resolvedPort = $Port
if (-not $NoAutoPortFallback) {
    $resolvedPort = Get-AvailablePort -BindAddress $BindHost -PreferredPort $Port
    if ($resolvedPort -ne $Port) {
        Write-Host "[RUN][DEV] 포트 $Port 사용 불가 -> $resolvedPort 로 자동 전환"
    }
}

$py = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$py = [System.IO.Path]::GetFullPath($py)
if (-not (Test-Path $py)) {
    throw "가상환경 파이썬을 찾을 수 없습니다: $py"
}

$args = @(
    "-m", "uvicorn", "app.main:app",
    "--reload",
    "--host", $BindHost,
    "--port", "$resolvedPort"
)

if ($UseSsl) {
    $keyPath = Resolve-AbsolutePath -Path $SslKeyFile
    $certPath = Resolve-AbsolutePath -Path $SslCertFile
    if (-not (Test-Path $keyPath)) { throw "SSL 키 파일을 찾을 수 없습니다: $keyPath" }
    if (-not (Test-Path $certPath)) { throw "SSL 인증서 파일을 찾을 수 없습니다: $certPath" }
    $args += @("--ssl-keyfile", $keyPath, "--ssl-certfile", $certPath)
}

Write-Host "[RUN][DEV] command: $py $($args -join ' ')"
Write-Host "[RUN][DEV] URL: $([string]::Concat(($UseSsl ? 'https' : 'http'), '://', $BindHost, ':', $resolvedPort, '/'))"
if ($CheckOnly) {
    Write-Host "[RUN][DEV] CheckOnly 모드 완료"
    exit 0
}

& $py @args
