param(
    [switch]$Mock,
    [switch]$ForceRestart,
    [switch]$ForceDependencySync,
    [switch]$NoBrowser,
    [string]$OpenPath = "/projects"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Root = $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Runtime = Join-Path $Root ".runtime"
$Logs = Join-Path $Root "logs"
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvSitePackages = Join-Path $Venv "Lib\site-packages"
$Requirements = Join-Path $Backend "requirements.txt"
$PackageJson = Join-Path $Frontend "package.json"
$PackageLock = Join-Path $Frontend "package-lock.json"
$LauncherLog = Join-Path $Logs "launcher.log"
$ApiPort = 8000
$FrontendPort = 5188
$StartedServices = [Collections.Generic.List[string]]::new()

New-Item -ItemType Directory -Force -Path $Runtime, $Logs | Out-Null

if ($Mock) {
    $mockRuntime = Join-Path $Runtime "mock"
    New-Item -ItemType Directory -Force -Path $mockRuntime | Out-Null
    $env:APP_ENV = "mock"
    $env:DATABASE_URL = "sqlite:///" + ((Join-Path $mockRuntime "app.db") -replace '\\', '/')
    $env:MEDIA_ROOT = Join-Path $mockRuntime "media"
    $env:BROKER_KIND = "thread"
    $env:AI_MODE = "mock"
    $env:MOCK_DEFAULT_SCENARIO = "success"
    $env:TEXT_PROVIDER = "mock"
    $env:IMAGE_PROVIDER = "mock"
    $env:VIDEO_PROVIDER = "mock"
    $env:AUDIO_PROVIDER = "mock"
    $bundledFfmpeg = Join-Path $Root "tools\ffmpeg.exe"
    if (Test-Path -LiteralPath $bundledFfmpeg) { $env:FFMPEG_PATH = $bundledFfmpeg }
}

function Write-LauncherLog {
    param([string]$Message, [string]$Level = "INFO")
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Write-Host $line
    Add-Content -LiteralPath $LauncherLog -Value $line -Encoding UTF8
}

function Stop-WithError {
    param([string]$Message)
    Write-LauncherLog $Message "ERROR"
    throw $Message
}

function Get-CombinedHash {
    param([string[]]$Paths)
    $parts = foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path) {
            $fileStream = [IO.File]::OpenRead($path)
            $fileSha = [Security.Cryptography.SHA256]::Create()
            try {
                ([BitConverter]::ToString($fileSha.ComputeHash($fileStream))).Replace("-", "")
            } finally {
                $fileSha.Dispose()
                $fileStream.Dispose()
            }
        } else {
            "missing:$path"
        }
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($parts -join "|"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "")
    } finally {
        $sha.Dispose()
    }
}

function Get-StoredValue {
    param([string]$Name)
    $path = Join-Path $Runtime $Name
    if (Test-Path -LiteralPath $path) {
        return (Get-Content -LiteralPath $path -Raw).Trim()
    }
    return ""
}

function Set-StoredValue {
    param([string]$Name, [string]$Value)
    Set-Content -LiteralPath (Join-Path $Runtime $Name) -Value $Value -Encoding UTF8
}

function Test-PythonEnvironment {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    & $VenvPython -c "import sys" 2>$null
    return $LASTEXITCODE -eq 0
}

function Ensure-PythonEnvironment {
    if (Test-PythonEnvironment) {
        Write-LauncherLog "Python environment ready: $Venv"
        return
    }
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        Stop-WithError "Python is not available on PATH. Install Python 3.10+ and run again."
    }
    Write-LauncherLog "Creating or repairing Python environment: $Venv"
    $venvArgs = @("-m", "venv")
    if (Test-Path -LiteralPath $Venv) { $venvArgs += "--upgrade" }
    $venvArgs += $Venv
    & $python.Source @venvArgs | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0 -or -not (Test-PythonEnvironment)) {
        Stop-WithError "Unable to create the Python environment."
    }
}

function Sync-BackendDependencies {
    $hash = Get-CombinedHash @($Requirements)
    $needsSync = $ForceDependencySync -or ((Get-StoredValue "backend-requirements.sha256") -ne $hash)
    if (-not $needsSync) {
        Write-LauncherLog "Backend dependencies unchanged."
        return $false
    }
    Write-LauncherLog "Synchronizing backend dependencies..."
    # This machine's portable Python exposes D:\lib before the venv site-packages.
    # Ignore globally visible distributions so the project receives its pinned copies.
    & $VenvPython -m pip install --ignore-installed -r $Requirements | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Backend dependency installation failed." }
    & $VenvPython -m pip check | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Backend dependency verification failed." }
    Set-StoredValue "backend-requirements.sha256" $hash
    return $true
}

function Sync-FrontendDependencies {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npm) { Stop-WithError "npm is not available on PATH. Install Node.js and run again." }
    $hash = Get-CombinedHash @($PackageJson, $PackageLock)
    $nodeModules = Join-Path $Frontend "node_modules"
    $needsSync = $ForceDependencySync -or -not (Test-Path -LiteralPath $nodeModules) -or ((Get-StoredValue "frontend-dependencies.sha256") -ne $hash)
    if (-not $needsSync) {
        Write-LauncherLog "Frontend dependencies unchanged."
        return $false
    }
    Write-LauncherLog "Synchronizing frontend dependencies..."
    Push-Location $Frontend
    try {
        if (Test-Path -LiteralPath $PackageLock) {
            & $npm.Source ci | ForEach-Object { Write-Host $_ }
        } else {
            & $npm.Source install | ForEach-Object { Write-Host $_ }
        }
        if ($LASTEXITCODE -ne 0) { Stop-WithError "Frontend dependency installation failed." }
    } finally {
        Pop-Location
    }
    Set-StoredValue "frontend-dependencies.sha256" $hash
    return $true
}

function Invoke-DatabaseMigration {
    Write-LauncherLog "Applying database migrations..."
    Push-Location $Backend
    try {
        if ($Mock) {
            & $VenvPython -m app.tools.mock_server --prepare-only | ForEach-Object { Write-Host $_ }
        } else {
            & $VenvPython -m alembic -c "alembic.ini" upgrade head | ForEach-Object { Write-Host $_ }
        }
        if ($LASTEXITCODE -ne 0) { Stop-WithError "Database migration failed. Check MySQL and .env settings." }
    } finally {
        Pop-Location
    }
}

function Get-StatePath {
    param([string]$Name)
    return Join-Path $Runtime ("{0}.json" -f $Name)
}

function Get-TrackedProcess {
    param([string]$Name)
    $statePath = Get-StatePath $Name
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    try {
        $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        if ([string]$state.root -ne $Root) { return $null }
        $process = Get-Process -Id ([int]$state.pid) -ErrorAction Stop
        $tickProperty = $state.PSObject.Properties["started_at_utc_ticks"]
        if ($null -ne $tickProperty -and $tickProperty.Value) {
            $expectedTicks = [long]$state.started_at_utc_ticks
        } else {
            $stamp = [regex]::Match((Get-Content -LiteralPath $statePath -Raw), '"started_at"\s*:\s*"([^"]+)"')
            if (-not $stamp.Success) { return $null }
            $expectedTicks = [DateTimeOffset]::Parse($stamp.Groups[1].Value).UtcDateTime.Ticks
        }
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
        if ([Math]::Abs(($actualTicks - $expectedTicks) / [TimeSpan]::TicksPerSecond) -gt 3) { return $null }
        return $process
    } catch {
        return $null
    }
}

function Save-TrackedProcess {
    param([string]$Name, [Diagnostics.Process]$Process)
    $state = [ordered]@{
        service = $Name
        pid = $Process.Id
        started_at_utc_ticks = $Process.StartTime.ToUniversalTime().Ticks
        root = $Root
    }
    $state | ConvertTo-Json | Set-Content -LiteralPath (Get-StatePath $Name) -Encoding UTF8
}

function Stop-TrackedProcess {
    param([string]$Name)
    $process = Get-TrackedProcess $Name
    if ($null -eq $process) {
        Remove-Item -LiteralPath (Get-StatePath $Name) -Force -ErrorAction SilentlyContinue
        return
    }
    Write-LauncherLog ("Stopping {0} (PID {1})..." -f $Name, $process.Id)
    & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError ("Unable to stop {0} (PID {1}). Try the stop shortcut as administrator." -f $Name, $process.Id)
    }
    Remove-Item -LiteralPath (Get-StatePath $Name) -Force -ErrorAction SilentlyContinue
}

function Get-ListeningPid {
    param([int]$Port)
    $pattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$"
    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match $pattern) { return [int]$Matches[1] }
    }
    return $null
}

function Test-ApiReady {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/api/health" -TimeoutSec 2
        $schema = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/openapi.json" -TimeoutSec 2
        $routeNames = @($schema.paths.PSObject.Properties.Name)
        # Windows PowerShell 5.1 can decode UTF-8 JSON titles incorrectly, so use
        # stable ASCII schema fields to distinguish this API from another app.
        return (
            $health.code -eq 0 -and
            $health.data.status -eq "up" -and
            $schema.info.version -eq "0.1.0" -and
            $routeNames -contains "/api/projects"
        )
    } catch {
        return $false
    }
}

function Test-FrontendReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$FrontendPort/src/main.ts" -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains("createApp") -and $response.Content.Contains("App.vue")
    } catch {
        return $false
    }
}

function Wait-UntilReady {
    param([string]$Name, [scriptblock]$Check, [Diagnostics.Process]$Process, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Check) {
            Write-LauncherLog "$Name is ready."
            return
        }
        if ($Process.HasExited) { Stop-WithError "$Name exited during startup. Check logs." }
        Start-Sleep -Milliseconds 500
    }
    Stop-WithError "$Name did not become ready within $Seconds seconds. Check logs."
}

function Ensure-Api {
    $tracked = Get-TrackedProcess "api"
    if ($null -ne $tracked -and (Test-ApiReady)) {
        Write-LauncherLog ("API already running (PID {0})." -f $tracked.Id)
        return
    }
    if ($null -ne $tracked) { Stop-TrackedProcess "api" }
    $portPid = Get-ListeningPid $ApiPort
    if ($null -ne $portPid) {
        if (Test-ApiReady) {
            Stop-WithError "An untracked AI Drama API is already using port $ApiPort. Close the old launcher windows or run the old stop shortcut once."
        }
        Stop-WithError "Port $ApiPort is occupied by another program (PID $portPid)."
    }
    Write-LauncherLog "Starting API on port $ApiPort..."
    $process = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") -WorkingDirectory $Backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "api.log") -RedirectStandardError (Join-Path $Logs "api.error.log") -PassThru
    Save-TrackedProcess "api" $process
    $script:StartedServices.Add("api") | Out-Null
    Wait-UntilReady "API" ${function:Test-ApiReady} $process 35
}

function Ensure-Worker {
    if ($Mock) {
        Write-LauncherLog "Mock mode: tasks run in the API thread pool; Redis worker is not required."
        return
    }
    $tracked = Get-TrackedProcess "worker"
    if ($null -ne $tracked) {
        Write-LauncherLog ("Worker already running (PID {0})." -f $tracked.Id)
        return
    }
    Write-LauncherLog "Starting Dramatiq worker..."
    $process = Start-Process -FilePath $VenvPython -ArgumentList @("-m", "dramatiq", "app.tasks", "--processes", "1", "--threads", "4") -WorkingDirectory $Backend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "worker.log") -RedirectStandardError (Join-Path $Logs "worker.error.log") -PassThru
    Save-TrackedProcess "worker" $process
    $script:StartedServices.Add("worker") | Out-Null
    Start-Sleep -Seconds 2
    if ($process.HasExited) { Stop-WithError "Worker exited during startup. Check logs\worker.error.log." }
    Write-LauncherLog ("Worker is running (PID {0})." -f $process.Id)
}

function Ensure-Frontend {
    $tracked = Get-TrackedProcess "frontend"
    if ($null -ne $tracked -and (Test-FrontendReady)) {
        Write-LauncherLog ("Frontend already running (PID {0})." -f $tracked.Id)
        return
    }
    if ($null -ne $tracked) { Stop-TrackedProcess "frontend" }
    $portPid = Get-ListeningPid $FrontendPort
    if ($null -ne $portPid) {
        if (Test-FrontendReady) {
            Stop-WithError "An untracked AI Drama frontend is already using port $FrontendPort. Close the old launcher windows or run the old stop shortcut once."
        }
        Stop-WithError "Port $FrontendPort is occupied by another program (PID $portPid)."
    }
    $npm = Get-Command npm.cmd -ErrorAction Stop
    Write-LauncherLog "Starting frontend on port $FrontendPort..."
    $process = Start-Process -FilePath $npm.Source -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort") -WorkingDirectory $Frontend -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs "frontend.log") -RedirectStandardError (Join-Path $Logs "frontend.error.log") -PassThru
    Save-TrackedProcess "frontend" $process
    $script:StartedServices.Add("frontend") | Out-Null
    Wait-UntilReady "Frontend" ${function:Test-FrontendReady} $process 35
}

$lockPath = Join-Path $Runtime "launcher.lock"
$lockStream = $null
try {
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        Stop-WithError "Another launcher instance is already running."
    }

    Write-LauncherLog "Launcher started for $Root"
    Ensure-PythonEnvironment
    if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
        $env:PYTHONPATH = $VenvSitePackages
    } else {
        $env:PYTHONPATH = "$VenvSitePackages;$($env:PYTHONPATH)"
    }
    $backendChanged = Sync-BackendDependencies
    $frontendChanged = Sync-FrontendDependencies

    $backendSourceFiles = @(Get-ChildItem -LiteralPath (Join-Path $Backend "app") -Recurse -File -Filter "*.py" | Sort-Object FullName | ForEach-Object FullName)
    $backendSourceHash = Get-CombinedHash $backendSourceFiles
    $envHash = (Get-CombinedHash @((Join-Path $Root ".env"))) + (":mock={0}:source={1}" -f [bool]$Mock, $backendSourceHash)
    $configChanged = (Get-StoredValue "backend-config.sha256") -ne $envHash

    if ($ForceRestart -or $backendChanged -or $configChanged) {
        Stop-TrackedProcess "worker"
        Stop-TrackedProcess "api"
    }
    if ($ForceRestart -or $frontendChanged) { Stop-TrackedProcess "frontend" }

    Invoke-DatabaseMigration
    Ensure-Api
    Ensure-Worker
    Ensure-Frontend
    Set-StoredValue "backend-config.sha256" $envHash

    if (-not $OpenPath.StartsWith("/")) { $OpenPath = "/projects" }
    $url = "http://localhost:$FrontendPort$OpenPath"
    if (-not $NoBrowser) {
        Start-Process $url
        Write-LauncherLog "Opened $url"
    }
    Write-LauncherLog "All services are ready."
    Write-Host ""
    Write-Host "AI Drama is ready: $url" -ForegroundColor Green
    Write-Host "Logs: $Logs"
} catch {
    foreach ($serviceName in @("frontend", "worker", "api")) {
        if ($StartedServices.Contains($serviceName)) {
            Stop-TrackedProcess $serviceName
        }
    }
    Write-Host ""
    Write-Host ("Startup failed: {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host "See $LauncherLog and service error logs for details."
    exit 1
} finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
}
