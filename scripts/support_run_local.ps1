Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "support\runtime"
$logDir = Join-Path $runtimeDir "logs"
$pidFile = Join-Path $runtimeDir "support-local-pids.json"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Get-RunningProcess([int]$ProcessId) {
  try {
    return Get-Process -Id $ProcessId -ErrorAction Stop
  } catch {
    return $null
  }
}

if (Test-Path $pidFile) {
  $old = Get-Content $pidFile -Raw | ConvertFrom-Json
  $serverOld = Get-RunningProcess -ProcessId ([int]$old.server_pid)
  $workerOld = Get-RunningProcess -ProcessId ([int]$old.worker_pid)
  if ($serverOld -or $workerOld) {
    Write-Host "[support-local] already running."
    Write-Host ("[support-local] server_pid={0} worker_pid={1}" -f $old.server_pid, $old.worker_pid)
    Write-Host "[support-local] open http://localhost:4310/en"
    exit 0
  }
}

$serverOut = Join-Path $logDir "support_server.out.log"
$serverErr = Join-Path $logDir "support_server.err.log"
$workerOut = Join-Path $logDir "support_worker.out.log"
$workerErr = Join-Path $logDir "support_worker.err.log"

$server = Start-Process -FilePath "node" -ArgumentList "support/server.mjs" -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $serverOut -RedirectStandardError $serverErr
$worker = Start-Process -FilePath "node" -ArgumentList "support/worker.mjs" -WorkingDirectory $repoRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr

Start-Sleep -Seconds 1

$payload = [ordered]@{
  started_at_utc = (Get-Date).ToUniversalTime().ToString("s") + "Z"
  server_pid = $server.Id
  worker_pid = $worker.Id
  server_url = "http://localhost:4310/en"
  server_log = $serverOut
  worker_log = $workerOut
}
$payload | ConvertTo-Json -Depth 4 | Set-Content -Path $pidFile -Encoding UTF8

Write-Host "[support-local] started."
Write-Host ("[support-local] server_pid={0} worker_pid={1}" -f $server.Id, $worker.Id)
Write-Host "[support-local] open http://localhost:4310/en"
Write-Host ("[support-local] logs: {0}" -f $logDir)
