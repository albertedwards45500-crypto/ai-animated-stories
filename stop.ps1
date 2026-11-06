param([switch]$KeepWindow)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Logs = Join-Path $Root "logs"
$LauncherLog = Join-Path $Logs "launcher.log"
$StopFailed = $false

New-Item -ItemType Directory -Force -Path $Runtime, $Logs | Out-Null

function Write-StopLog {
    param([string]$Message, [string]$Level = "INFO")
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
}

function Stop-RecordedService {
    param([string]$Name)
    $statePath = Join-Path $Runtime ("{0}.json" -f $Name)
    if (-not (Test-Path -LiteralPath $statePath)) {
        Write-StopLog "$Name is not recorded; skipped."
        return
    }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    } catch {
        Write-StopLog "$Name state is invalid; removing the stale record." "WARN"
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        return
    }
    if ([string]$state.root -ne $Root) {
        Write-StopLog "$Name state belongs to another project; skipped." "WARN"
        $script:StopFailed = $true
        return
    }
    try {
        $process = Get-Process -Id ([int]$state.pid) -ErrorAction Stop
        $tickProperty = $state.PSObject.Properties["started_at_utc_ticks"]
        if ($null -ne $tickProperty -and $tickProperty.Value) {
            $expectedTicks = [long]$state.started_at_utc_ticks
        } else {
            $stamp = [regex]::Match((Get-Content -LiteralPath $statePath -Raw), '"started_at"\s*:\s*"([^"]+)"')
            if (-not $stamp.Success) { throw "Missing process start time" }
            $expectedTicks = [DateTimeOffset]::Parse($stamp.Groups[1].Value).UtcDateTime.Ticks
        }
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
        if ([Math]::Abs(($actualTicks - $expectedTicks) / [TimeSpan]::TicksPerSecond) -gt 3) {
            Write-StopLog "$Name PID was reused by another process; removing the stale record." "WARN"
            Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
            return
        }
    } catch {
        Write-StopLog "$Name is no longer running."
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        return
    }
    Write-StopLog ("Stopping {0} (PID {1})..." -f $Name, $process.Id)
    & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-StopLog ("Unable to stop {0} (PID {1}); keeping its state record. Try this shortcut as administrator." -f $Name, $process.Id) "ERROR"
        $script:StopFailed = $true
        return
    }
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}

Stop-RecordedService "frontend"
Stop-RecordedService "worker"
Stop-RecordedService "api"
if ($StopFailed) {
    Write-StopLog "Some AI Drama services could not be stopped; see the messages above." "ERROR"
} else {
    Write-StopLog "Recorded AI Drama services stopped."
}

if ($KeepWindow) {
    Write-Host "Press Enter to close."
    [void](Read-Host)
}

if ($StopFailed) { exit 1 }
