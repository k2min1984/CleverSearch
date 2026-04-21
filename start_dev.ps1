param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsFromCaller
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $scriptDir "scripts\start_dev.ps1"

if (-not (Test-Path $target)) {
    throw "대상 스크립트를 찾을 수 없습니다: $target"
}

& pwsh -File $target @ArgsFromCaller
