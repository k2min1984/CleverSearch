param(
    [switch]$KillExisting,
    [switch]$CheckOnly,
    [string]$BindHost = "127.0.0.1",
    [int]$Port = 8000,
    [switch]$NoAutoPortFallback
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startDev = Join-Path $scriptDir "start_dev.ps1"

$args = @(
    "-EnvFile", ".env.yatap",
    "-BindHost", $BindHost,
    "-Port", "$Port"
)

if ($KillExisting) { $args += "-KillExisting" }
if ($CheckOnly) { $args += "-CheckOnly" }
if ($NoAutoPortFallback) { $args += "-NoAutoPortFallback" }

& pwsh -File $startDev @args
