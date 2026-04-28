param(
    [int]$Port = 8000
)

$ErrorActionPreference = "SilentlyContinue"

Write-Host "[STOP][8000] 대상 포트: $Port"

# 1) 포트 점유 프로세스 정리
$portOwners = Get-NetTCPConnection -LocalPort $Port -State Listen |
Select-Object -ExpandProperty OwningProcess -Unique

if ($portOwners) {
    foreach ($proc in $portOwners) {
        try {
            Stop-Process -Id $proc -Force -ErrorAction Stop
            Write-Host "[STOP][8000] 포트 점유 프로세스 종료: $proc"
        }
        catch {
            Write-Host "[STOP][8000] 포트 점유 프로세스 종료 실패: $proc"
        }
    }
}
else {
    Write-Host "[STOP][8000] LISTEN 점유 프로세스 없음"
}

# 2) uvicorn app.main:app 잔여 프로세스 정리
$uvicornPids = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
Where-Object { $_.CommandLine -match 'uvicorn\s+app\.main:app' } |
Select-Object -ExpandProperty ProcessId -Unique

if ($uvicornPids) {
    foreach ($proc in $uvicornPids) {
        try {
            Stop-Process -Id $proc -Force -ErrorAction Stop
            Write-Host "[STOP][8000] uvicorn 프로세스 종료: $proc"
        }
        catch {
            Write-Host "[STOP][8000] uvicorn 프로세스 종료 실패: $proc"
        }
    }
}
else {
    Write-Host "[STOP][8000] uvicorn app.main:app 프로세스 없음"
}

Start-Sleep -Seconds 1

$left = $null
for ($retry = 0; $retry -lt 5; $retry++) {
    $left = Get-NetTCPConnection -LocalPort $Port -State Listen |
    Select-Object LocalAddress, LocalPort, OwningProcess

    if (-not $left) { break }

    $leftOwners = $left | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $leftOwners) {
        try {
            Stop-Process -Id $ownerPid -Force -ErrorAction Stop
            Write-Host "[STOP][8000] 잔존 점유 프로세스 재종료: $ownerPid"
        }
        catch {
            Write-Host "[STOP][8000] 잔존 점유 프로세스 재종료 실패: $ownerPid"
        }
    }

    Start-Sleep -Milliseconds 700
}

# 마지막으로 한 번 더 조회해 잔존 점유를 확정합니다.
$left = Get-NetTCPConnection -LocalPort $Port -State Listen |
Select-Object LocalAddress, LocalPort, OwningProcess

if ($left) {
    Write-Host "[STOP][8000] 경고: 포트 점유 잔존"
    $left | Format-Table -AutoSize
    exit 1
}

Write-Host "[STOP][8000] 완료: 포트 $Port 해제됨"
exit 0
