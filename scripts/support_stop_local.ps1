Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "support\runtime"
$pidFile = Join-Path $runtimeDir "support-local-pids.json"

function Stop-IfRunning([int]$ProcessId, [string]$Name) {
  try {
    $proc = Get-Process -Id $ProcessId -ErrorAction Stop
    Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    Write-Host ("[support-local] stopped {0} pid={1}" -f $Name, $ProcessId)
  } catch {
    Write-Host ("[support-local] {0} pid={1} already stopped" -f $Name, $ProcessId)
  }
}

if (!(Test-Path $pidFile)) {
  Write-Host "[support-local] pid file not found. Nothing to stop."
  exit 0
}

$state = Get-Content $pidFile -Raw | ConvertFrom-Json
if ($state.server_pid) {
  Stop-IfRunning -ProcessId ([int]$state.server_pid) -Name "server"
}
if ($state.worker_pid) {
  Stop-IfRunning -ProcessId ([int]$state.worker_pid) -Name "worker"
}

Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "[support-local] shutdown complete."
