param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'supervise')]
    [string]$Action = 'status'
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $Root 'backend'
$Python = Join-Path $BackendDir '.venv\Scripts\python.exe'
$EnvFile = Join-Path $BackendDir '.env'
$Cloudflared = (Get-Command cloudflared.exe -ErrorAction SilentlyContinue).Source
if (-not $Cloudflared) { $Cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source }
$Tailscale = (Get-Command tailscale.exe -ErrorAction SilentlyContinue).Source
if (-not $Tailscale) { $Tailscale = (Get-Command tailscale -ErrorAction SilentlyContinue).Source }
if (-not $Tailscale) {
    foreach ($candidate in @((Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'), (Join-Path ${env:ProgramFiles(x86)} 'Tailscale\tailscale.exe'))) {
        if ($candidate -and (Test-Path $candidate)) { $Tailscale = $candidate; break }
    }
}
$ConfigPath = Join-Path $Root 'aetrix-stack.env'
$StateDir = Join-Path $Root '.tmp\aetrix\stack'
$StatePath = Join-Path $StateDir 'state.json'
$StopPath = Join-Path $StateDir 'stop.request'
$LogPath = Join-Path $StateDir 'stack.log'
$BackendLog = Join-Path $StateDir 'backend.log'
$BackendErr = Join-Path $StateDir 'backend.err.log'
$WorkerLog = Join-Path $StateDir 'worker.log'
$WorkerErr = Join-Path $StateDir 'worker.err.log'
$TunnelLog = Join-Path $StateDir 'tunnel.log'
$TunnelErr = Join-Path $StateDir 'tunnel.err.log'
$MonitorLog = Join-Path $StateDir 'monitor.log'
$MonitorErr = Join-Path $StateDir 'monitor.err.log'

$Cfg = @{}
if (Test-Path $ConfigPath) {
    foreach ($line in Get-Content -Path $ConfigPath) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $Cfg[$Matches[1]] = $Matches[2].Trim().Trim('"')
        }
    }
}

function Get-Setting([string]$Name, [string]$Default = '') {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($value)) { return $value.Trim() }
    if ($Cfg.ContainsKey($Name)) { return [string]$Cfg[$Name] }
    return $Default
}

$Mode = Get-Setting 'AETRIX_TUNNEL_MODE' 'named'
$PublicUrl = (Get-Setting 'AETRIX_PUBLIC_API_URL' '').TrimEnd('/')
$FrontendUrl = (Get-Setting 'AETRIX_FRONTEND_URL' 'https://aetrix.pages.dev').TrimEnd('/')
$TunnelName = Get-Setting 'AETRIX_TUNNEL_NAME' 'aetrix'
$AllowQuick = Get-Setting 'AETRIX_ALLOW_QUICK_TUNNEL' '0'
$Interval = [Math]::Max(5, [int](Get-Setting 'AETRIX_MONITOR_INTERVAL_SECONDS' '10'))
$HealthTimeout = [Math]::Max(20, [int](Get-Setting 'AETRIX_HEALTH_TIMEOUT_SECONDS' '90'))
$MaxRestarts = [Math]::Max(1, [int](Get-Setting 'AETRIX_MAX_RESTARTS' '5'))
$RestartWindow = [Math]::Max(1, [int](Get-Setting 'AETRIX_RESTART_WINDOW_MINUTES' '15'))
$LocalUrl = 'http://127.0.0.1:8000'
$BackendPid = 0
$WorkerPid = 0
$TunnelPid = 0
$MonitorPid = 0
$BackendStartedByUs = $false
$WorkerStartedByUs = $false
$TunnelStartedByUs = $false
$RestartTimes = New-Object System.Collections.ArrayList

function Initialize-State {
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
}

function Write-Log([string]$Message, [string]$Level = 'INFO') {
    Initialize-State
    $line = '{0} [{1}] {2}' -f (Get-Date -Format o), $Level, $Message
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    if ($Level -eq 'ERROR') { Write-Host $Message -ForegroundColor Red }
    elseif ($Level -eq 'WARN') { Write-Host $Message -ForegroundColor Yellow }
    else { Write-Host $Message }
}

function Get-State {
    if (-not (Test-Path $StatePath)) { return $null }
    try { return Get-Content -Raw $StatePath | ConvertFrom-Json } catch { return $null }
}

function Save-State {
    Initialize-State
    $state = [ordered]@{
        backendPid = $BackendPid
        workerPid = $WorkerPid
        tunnelPid = $TunnelPid
        monitorPid = $MonitorPid
        publicUrl = $PublicUrl
        mode = $Mode
        frontendUrl = $FrontendUrl
        updatedAt = (Get-Date).ToString('o')
    }
    $state | ConvertTo-Json | Set-Content -Path $StatePath -Encoding UTF8
}

function Remove-State {
    if (Test-Path $StatePath) { Remove-Item $StatePath -Force }
    if (Test-Path $StopPath) { Remove-Item $StopPath -Force }
}

function Get-ProcessRecord([int]$ProcessId) {
    if ($ProcessId -le 0) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-BackendProcess($Process) {
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    return ([string]$Process.CommandLine -match 'uvicorn') -and
        ([string]$Process.CommandLine -match 'app\.main:app') -and
        ([string]$Process.CommandLine -match '--port\s+8000')
}

function Test-TunnelProcess($Process) {
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    $cmd = [string]$Process.CommandLine
    return ($cmd -match 'cloudflared') -and ($cmd -match 'tunnel') -and
        (($cmd -match 'run') -or ($cmd -match '--url'))
}

function Test-WorkerProcess($Process) {
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    return ([string]$Process.CommandLine -match 'app\.worker')
}

function Invoke-TailscaleCli {
    # Every Tailscale call is bounded. While the daemon is between states the
    # CLI can wait for a transition instead of answering, and an unbounded call
    # makes the whole startup command hang without printing anything.
    param([string[]]$Arguments, [int]$TimeoutSeconds = 20)
    if ([string]::IsNullOrWhiteSpace($Tailscale)) {
        return [pscustomobject]@{ ExitCode = -1; Output = 'Tailscale is not installed or not on PATH.' }
    }
    Initialize-State
    $outFile = Join-Path $StateDir 'tailscale.out.log'
    $errFile = Join-Path $StateDir 'tailscale.err.log'
    try {
        $process = Start-Process -FilePath $Tailscale -ArgumentList $Arguments -WorkingDirectory $Root `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile -WindowStyle Hidden -PassThru
    } catch {
        return [pscustomobject]@{ ExitCode = -1; Output = $_.Exception.Message }
    }
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{
            ExitCode = -1
            Output = "tailscale $($Arguments -join ' ') did not answer within $TimeoutSeconds seconds."
        }
    }
    $output = ''
    foreach ($path in @($outFile, $errFile)) {
        if (Test-Path $path) { $output += (Get-Content -Raw $path) + "`n" }
    }
    return [pscustomobject]@{ ExitCode = [int]$process.ExitCode; Output = $output.Trim() }
}

function Get-TailscaleStatus {
    $result = Invoke-TailscaleCli -Arguments @('status', '--json') -TimeoutSeconds 20
    if ($result.ExitCode -ne 0) { return $null }
    try { return ($result.Output | ConvertFrom-Json) } catch { return $null }
}

function Test-TailscaleBackend {
    $status = Get-TailscaleStatus
    return ($null -ne $status -and [string]$status.BackendState -eq 'Running')
}

function Ensure-TailscaleService {
    $service = Get-Service -Name 'Tailscale' -ErrorAction SilentlyContinue
    if ($null -eq $service -or $service.Status -eq 'Running') { return }
    Write-Log "The Tailscale service is '$($service.Status)'; starting it." 'WARN'
    try {
        Start-Service -Name 'Tailscale' -ErrorAction Stop
    } catch {
        throw "The Tailscale service is '$($service.Status)' and could not be started ($($_.Exception.Message)). Start it once from an elevated prompt with: Start-Service Tailscale"
    }
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if ((Get-Service -Name 'Tailscale' -ErrorAction SilentlyContinue).Status -eq 'Running') { return }
    }
    throw 'The Tailscale service did not reach Running within 30 seconds.'
}

function Start-TailscaleClient {
    # The daemon alone is not enough on Windows: the IPN client drives the
    # backend. After a login-time restart where the tray app did not come back,
    # tailscaled sits in NoState and neither MagicDNS nor Funnel works, so the
    # public API disappears even though the service is "RUNNING".
    if ([string]::IsNullOrWhiteSpace($Tailscale)) { return }
    $ipn = Join-Path (Split-Path -Parent $Tailscale) 'tailscale-ipn.exe'
    if (-not (Test-Path $ipn)) { return }
    $running = Get-CimInstance Win32_Process -Filter "Name='tailscale-ipn.exe'" -ErrorAction SilentlyContinue
    if ($null -ne $running) { return }
    Write-Log 'Tailscale IPN client is not running; starting it so the daemon can connect.' 'WARN'
    # The tray app is a long-lived GUI process. Redirect its streams so it never
    # inherits this script's stdout/stderr: a caller that pipes the launcher
    # (CI, a wrapper, a logon task) would otherwise wait for the tray app to exit.
    Initialize-State
    Start-Process -FilePath $ipn `
        -RedirectStandardOutput (Join-Path $StateDir 'tailscale-ipn.out.log') `
        -RedirectStandardError (Join-Path $StateDir 'tailscale-ipn.err.log') `
        -WindowStyle Hidden | Out-Null
}

function Ensure-TailscaleRunning {
    if ([string]::IsNullOrWhiteSpace($Tailscale)) {
        throw 'Tailscale is not installed or not on PATH. Install it once with "winget install --id Tailscale.Tailscale -e" and sign in.'
    }
    Ensure-TailscaleService
    if (Test-TailscaleBackend) { return }
    Start-TailscaleClient
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-TailscaleBackend) {
            Write-Log 'Tailscale backend connected.'
            return
        }
    }
    $detail = (Invoke-TailscaleCli -Arguments @('status') -TimeoutSeconds 10).Output
    throw "Tailscale is installed but its backend never reached Running. Open the Tailscale app, sign in, and retry. tailscale status: $detail"
}

function Get-TailscaleDnsName {
    if ([string]::IsNullOrWhiteSpace($Tailscale)) {
        throw 'Tailscale is not installed or not on PATH. Install Tailscale and sign in once.'
    }
    $status = Get-TailscaleStatus
    if ($null -eq $status) {
        throw 'Tailscale is not signed in or not running. Open the Tailscale app and sign in.'
    }
    if ([string]$status.BackendState -ne 'Running') {
        throw "Tailscale backend is '$($status.BackendState)', not Running. Open the Tailscale app and sign in."
    }
    if ($null -eq $status.Self -or [string]::IsNullOrWhiteSpace([string]$status.Self.DNSName)) {
        throw 'Tailscale has no MagicDNS name. Enable MagicDNS and HTTPS in the Tailscale admin console.'
    }
    return ([string]$status.Self.DNSName).TrimEnd('.')
}

function Test-TailscaleFunnel {
    # A `serve` route prints the same https://<machine>.ts.net URL but is
    # reachable only inside the tailnet. The public route is reported healthy
    # only when Tailscale itself says Funnel is on for it.
    if ([string]::IsNullOrWhiteSpace($Tailscale)) { return $false }
    if (-not (Test-TailscaleBackend)) { return $false }
    $result = Invoke-TailscaleCli -Arguments @('funnel', 'status') -TimeoutSeconds 15
    if ($result.ExitCode -ne 0) { return $false }
    return ($result.Output -match 'Funnel on') -and ($result.Output -match 'https://[a-z0-9.-]+\.ts\.net')
}

function Test-TunnelAlive {
    if ($script:Mode -eq 'tailscale') { return (Test-TailscaleFunnel) }
    return (Test-TunnelProcess (Get-ProcessRecord $script:TunnelPid))
}

function Disable-TailscaleFunnel {
    if ([string]::IsNullOrWhiteSpace($Tailscale)) { return }
    # Disabling an already-disabled route is a normal idempotent outcome, so
    # Tailscale's own "no handler" wording is accepted rather than thrown.
    $result = Invoke-TailscaleCli -Arguments @('funnel', '--https=443', '--set-path=/', 'off') -TimeoutSeconds 30
    if ($result.ExitCode -ne 0) {
        $detail = $result.Output
        if ($detail -match 'handler does not exist|No serve config') {
            Write-Log 'Tailscale Funnel root route was already disabled.'
        } else {
            Write-Log ("Could not disable the Tailscale Funnel root route: " + $detail) 'WARN'
        }
    } else {
        Write-Log 'Tailscale Funnel root route disabled.'
    }
}

function Stop-Tunnel {
    if ($script:Mode -eq 'tailscale') {
        if (Test-TailscaleFunnel) {
            Disable-TailscaleFunnel
        } else {
            Write-Log 'Tailscale Funnel root route is already disabled.'
        }
        $script:TunnelPid = 0
        return
    }
    Stop-OwnedProcess $script:TunnelPid 'tunnel'
}

function Test-MonitorProcess($Process) {
    if ($null -eq $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    $cmd = [string]$Process.CommandLine
    return ($cmd -match 'aetrix-stack\.ps1') -and ($cmd -match 'supervise')
}

function Get-ListenerPid([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $connection) { return 0 }
    return [int]$connection.OwningProcess
}

function Invoke-Probe {
    param(
        [string]$Uri,
        [string]$Method = 'GET',
        [hashtable]$Headers = @{},
        [string]$Body = $null,
        [int]$Timeout = 20
    )
    $params = @{
        Uri = $Uri
        Method = $Method
        Headers = $Headers
        TimeoutSec = $Timeout
        UseBasicParsing = $true
    }
    if (-not [string]::IsNullOrEmpty($Body)) { $params['Body'] = $Body }
    try {
        $response = Invoke-WebRequest @params
        return [pscustomobject]@{
            Status = [int]$response.StatusCode
            Body = [string]$response.Content
            Headers = $response.Headers
        }
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) { return $null }
        $body = ''
        try {
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $body = $reader.ReadToEnd()
            $reader.Close()
        } catch { }
        return [pscustomobject]@{
            Status = [int]$response.StatusCode
            Body = $body
            Headers = $response.Headers
        }
    }
}

function Get-HeaderValue($Response, [string]$Name) {
    if ($null -eq $Response) { return '' }
    $value = $Response.Headers[$Name]
    if ($null -eq $value) { return '' }
    return ([string]$value).Trim()
}

function Wait-For([scriptblock]$Check, [int]$TimeoutSeconds, [string]$Description) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Check) { return $true }
        Start-Sleep -Seconds 2
    }
    Write-Log "Timed out waiting for $Description ($TimeoutSeconds s)." 'ERROR'
    return $false
}

function Test-LocalHealth {
    $r = Invoke-Probe "$LocalUrl/health" -Timeout 5
    return ($null -ne $r -and $r.Status -eq 200)
}

function Test-LocalReady {
    $r = Invoke-Probe "$LocalUrl/ready" -Timeout 20
    if ($null -eq $r -or $r.Status -ne 200) { return $false }
    try { return (($r.Body | ConvertFrom-Json).database -eq 'ok') } catch { return $false }
}

function Test-PublicHealth {
    if ([string]::IsNullOrWhiteSpace($PublicUrl)) { return $false }
    $r = Invoke-Probe "$PublicUrl/health" -Timeout 15
    if ($null -eq $r -or $r.Status -ne 200) { return $false }
    try { return (($r.Body | ConvertFrom-Json).status -eq 'ok') } catch { return $false }
}

function Test-PublicReady {
    if ([string]::IsNullOrWhiteSpace($PublicUrl)) { return $false }
    $r = Invoke-Probe "$PublicUrl/ready" -Timeout 20
    if ($null -eq $r -or $r.Status -ne 200) { return $false }
    try { return (($r.Body | ConvertFrom-Json).database -eq 'ok') } catch { return $false }
}

function Stop-OwnedProcess([int]$ProcessId, [string]$Kind) {
    if ($ProcessId -le 0) { return }
    $process = Get-ProcessRecord $ProcessId
    if ($null -eq $process) { return }
    $isOurs = $false
    if ($Kind -eq 'backend') { $isOurs = Test-BackendProcess $process }
    elseif ($Kind -eq 'worker') { $isOurs = Test-WorkerProcess $process }
    elseif ($Kind -eq 'tunnel') { $isOurs = Test-TunnelProcess $process }
    elseif ($Kind -eq 'monitor') { $isOurs = Test-MonitorProcess $process }
    if (-not $isOurs) {
        Write-Log "Refusing to stop PID ${ProcessId}: it is not this project's $Kind process." 'WARN'
        return
    }
    Write-Log "Stopping $Kind PID $ProcessId ..."
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 20; $i++) {
        if ($null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 500
    }
    Write-Log "$Kind PID $ProcessId did not exit within 10 seconds." 'ERROR'
}

function Test-Configuration {
    if (-not (Test-Path $Python)) { throw "No backend virtual environment at $Python." }
    if (-not (Test-Path $EnvFile)) { throw "backend\.env is missing. Copy backend\.env.example and fill it in." }
    if ($Mode -notin @('named', 'quick', 'tailscale')) { throw "AETRIX_TUNNEL_MODE must be 'named', 'quick' or 'tailscale'." }
    if ($Mode -in @('named', 'quick') -and [string]::IsNullOrWhiteSpace($Cloudflared)) { throw 'cloudflared.exe is not installed or not on PATH.' }

    if ($Mode -eq 'quick') {
        if ($AllowQuick -ne '1') {
            throw 'Quick tunnels are development-only. Set AETRIX_ALLOW_QUICK_TUNNEL=1 only for a temporary test; they cannot provide permanent frontend connectivity.'
        }
        Write-Log 'DEVELOPMENT MODE: a quick tunnel will get a new hostname on every restart.' 'WARN'
    } elseif ($Mode -eq 'tailscale') {
        $dnsName = Get-TailscaleDnsName
        if ([string]::IsNullOrWhiteSpace($PublicUrl)) { $script:PublicUrl = "https://$dnsName" }
        $uri = $null
        if (-not [uri]::TryCreate($PublicUrl, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
            throw "AETRIX_PUBLIC_API_URL must be an absolute HTTPS URL; got '$PublicUrl'."
        }
        if ($uri.Host -ne $dnsName -or $uri.Host -notlike '*.ts.net') {
            throw "AETRIX_PUBLIC_API_URL must be https://$dnsName for the current Tailscale Funnel."
        }
        Write-Log "Tailscale Funnel target: $dnsName -> $LocalUrl."
    } else {
        if ([string]::IsNullOrWhiteSpace($PublicUrl)) {
            throw 'AETRIX_PUBLIC_API_URL is not set. Set the stable HTTPS API origin, e.g. https://api.example.com.'
        }
        $uri = $null
        if (-not [uri]::TryCreate($PublicUrl, [UriKind]::Absolute, [ref]$uri) -or $uri.Scheme -ne 'https') {
            throw "AETRIX_PUBLIC_API_URL must be an absolute HTTPS URL; got '$PublicUrl'."
        }
        if ($uri.Host -match '^(localhost|127\.0\.0\.1|0\.0\.0\.0)$' -or $uri.Host -like '*.trycloudflare.com') {
            throw 'AETRIX_PUBLIC_API_URL must be a stable public hostname, not localhost or a trycloudflare.com quick tunnel.'
        }
        $token = [Environment]::GetEnvironmentVariable('AETRIX_TUNNEL_TOKEN')
        $cert = [Environment]::GetEnvironmentVariable('TUNNEL_ORIGIN_CERT')
        if ([string]::IsNullOrWhiteSpace($cert)) { $cert = Join-Path $HOME '.cloudflared\cert.pem' }
        if ([string]::IsNullOrWhiteSpace($token) -and -not (Test-Path $cert)) {
            throw 'Stable tunnel blocked: no tunnel token and no cloudflared certificate. Run "cloudflared tunnel login" interactively, or set AETRIX_TUNNEL_TOKEN for a remotely managed tunnel.'
        }
        if ([string]::IsNullOrWhiteSpace($token) -and [string]::IsNullOrWhiteSpace($TunnelName)) {
            throw 'AETRIX_TUNNEL_NAME is required when using a cloudflared certificate.'
        }
    }

    $frontendEnv = Join-Path $Root 'frontend\.env'
    $frontendApi = ''
    if (Test-Path $frontendEnv) {
        foreach ($line in Get-Content $frontendEnv) {
            if ($line -match '^\s*VITE_AETRIX_API_URL\s*=\s*(.*)$') {
                $frontendApi = $Matches[1].Trim().Trim('"').TrimEnd('/')
                break
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($frontendApi)) {
        throw 'frontend\.env has no VITE_AETRIX_API_URL. The deployed frontend would not know the engine origin.'
    }
    if ($Mode -in @('named', 'tailscale') -and $frontendApi -ne $PublicUrl) {
        throw "frontend\.env points at '$frontendApi' but the stable API is '$PublicUrl'. Update it once, rebuild and redeploy Pages."
    }
}

function Start-BackendProcess {
    $listener = Get-ListenerPid 8000
    if ($listener -gt 0) {
        $process = Get-ProcessRecord $listener
        if (Test-BackendProcess $process) {
            $script:BackendPid = $listener
            Write-Log "Reusing the existing Aetrix backend on $LocalUrl (PID $listener)."
            Save-State
            if (-not (Wait-For { Test-LocalReady } $HealthTimeout 'database readiness')) {
                throw 'The existing backend does not reach database readiness.'
            }
            return
        }
        throw "Port 8000 is held by PID $listener, which is not this project's uvicorn app.main:app."
    }

    Initialize-State
    foreach ($path in @($BackendLog, $BackendErr)) {
        if (Test-Path $path) { Move-Item $path "$path.previous" -Force }
    }
    Write-Log "Starting FastAPI on $LocalUrl ..."
    $arguments = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'info')
    $process = Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $BackendLog -RedirectStandardError $BackendErr -WindowStyle Hidden -PassThru
    $script:BackendPid = [int]$process.Id
    $script:BackendStartedByUs = $true
    Save-State
    if (-not (Wait-For { Test-LocalHealth } $HealthTimeout 'backend /health')) {
        Stop-OwnedProcess $script:BackendPid 'backend'
        throw "The backend did not answer $LocalUrl/health. See $BackendErr."
    }
    if (-not (Wait-For { Test-LocalReady } $HealthTimeout 'database readiness')) {
        Stop-OwnedProcess $script:BackendPid 'backend'
        throw "The backend answered /health but /ready failed. Check backend\.env and the database."
    }
    Write-Log "Backend ready (PID $script:BackendPid)."
}

function Start-WorkerProcess {
    # The worker is the only process that leases correction jobs, so a queued
    # job is never picked up without it. It parks jobs with PIPELINE_UNAVAILABLE
    # while the live provider is disabled; that is the honest state, not a
    # startup failure.
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { Test-WorkerProcess $_ } | Select-Object -First 1
    if ($null -ne $existing) {
        $script:WorkerPid = [int]$existing.ProcessId
        Write-Log "Reusing the existing Aetrix worker (PID $script:WorkerPid)."
        Save-State
        return
    }

    Initialize-State
    foreach ($path in @($WorkerLog, $WorkerErr)) {
        if (Test-Path $path) { Move-Item $path "$path.previous" -Force }
    }
    Write-Log 'Starting the correction worker ...'
    $arguments = @('-m', 'app.worker')
    $process = Start-Process -FilePath $Python -ArgumentList $arguments -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $WorkerLog -RedirectStandardError $WorkerErr -WindowStyle Hidden -PassThru
    $script:WorkerPid = [int]$process.Id
    $script:WorkerStartedByUs = $true
    Save-State
    if (-not (Wait-For { Test-WorkerProcess (Get-ProcessRecord $script:WorkerPid) } 30 'the worker process')) {
        Stop-OwnedProcess $script:WorkerPid 'worker'
        throw "The worker did not stay up. See $WorkerErr."
    }
    Write-Log "Worker started (PID $script:WorkerPid)."
}

function Stop-Worker {
    Stop-OwnedProcess $script:WorkerPid 'worker'
    $script:WorkerPid = 0
}

function Find-QuickTunnelUrl {
    if (-not (Test-Path $TunnelErr)) { return '' }
    $match = [regex]::Match((Get-Content -Raw $TunnelErr), 'https://[a-z0-9-]+\.trycloudflare\.com')
    if ($match.Success) { return $match.Value }
    return ''
}

function Start-TunnelProcess {
    Initialize-State
    foreach ($path in @($TunnelLog, $TunnelErr)) {
        if (Test-Path $path) { Move-Item $path "$path.previous" -Force }
    }

    if ($Mode -eq 'tailscale') {
        if ([string]::IsNullOrWhiteSpace($PublicUrl)) { throw 'Tailscale Funnel needs AETRIX_PUBLIC_API_URL.' }
        Write-Log "Starting Tailscale Funnel for $PublicUrl ..."
        $result = Invoke-TailscaleCli -Arguments @('funnel', '--bg', '--yes', '--https=443', $LocalUrl) -TimeoutSeconds 60
        if ($result.ExitCode -ne 0) {
            throw "Tailscale Funnel failed: $($result.Output). Funnel must be allowed for this device, with HTTPS certificates and MagicDNS enabled, in the Tailscale admin console."
        }
        $script:TunnelPid = 0
        $script:TunnelStartedByUs = $true
        Save-State
        if (-not (Wait-For { Test-PublicHealth } $HealthTimeout 'Tailscale public /health')) {
            Disable-TailscaleFunnel
            throw "Tailscale Funnel was configured, but $PublicUrl/health did not answer. Check Funnel status, HTTPS and MagicDNS."
        }
        Write-Log "Tailscale Funnel ready ($PublicUrl)."
        return
    }

    $arguments = @()
    $token = [Environment]::GetEnvironmentVariable('AETRIX_TUNNEL_TOKEN')
    if ($Mode -eq 'quick') {
        $arguments = @('tunnel', '--url', $LocalUrl, '--no-autoupdate', '--loglevel', 'info')
        Write-Log 'Starting a temporary Cloudflare quick tunnel (not a stable production host).' 'WARN'
    } elseif (-not [string]::IsNullOrWhiteSpace($token)) {
        $arguments = @('tunnel', 'run', '--no-autoupdate')
        Write-Log 'Starting the named Cloudflare tunnel using AETRIX_TUNNEL_TOKEN.'
    } else {
        if ([string]::IsNullOrWhiteSpace($TunnelName)) { throw 'AETRIX_TUNNEL_NAME is required for a named tunnel.' }
        $arguments = @('tunnel', 'run', $TunnelName, '--no-autoupdate')
        Write-Log "Starting named Cloudflare tunnel '$TunnelName' ..."
    }

    $previousToken = $env:TUNNEL_TOKEN
    if (-not [string]::IsNullOrWhiteSpace($token)) { $env:TUNNEL_TOKEN = $token }
    try {
        $process = Start-Process -FilePath $Cloudflared -ArgumentList $arguments -WorkingDirectory $Root `
            -RedirectStandardOutput $TunnelLog -RedirectStandardError $TunnelErr -WindowStyle Hidden -PassThru
        $script:TunnelPid = [int]$process.Id
        $script:TunnelStartedByUs = $true
    } finally {
        $env:TUNNEL_TOKEN = $previousToken
    }
    Save-State

    if ($Mode -eq 'quick') {
        if (-not (Wait-For {
                    $url = Find-QuickTunnelUrl
                    if (-not [string]::IsNullOrWhiteSpace($url)) {
                        $script:PublicUrl = $url.TrimEnd('/')
                        Save-State
                        return $true
                    }
                    return $false
                } 60 'quick-tunnel hostname')) {
            Stop-OwnedProcess $script:TunnelPid 'tunnel'
            throw "cloudflared did not publish a quick-tunnel URL. See $TunnelErr."
        }
    }

    if (-not (Wait-For { Test-PublicHealth } $HealthTimeout 'public /health')) {
        Stop-OwnedProcess $script:TunnelPid 'tunnel'
        throw "The tunnel process started, but $PublicUrl/health did not answer. Check DNS, ingress and $TunnelErr."
    }
    Write-Log "Tunnel ready (PID $script:TunnelPid, $PublicUrl)."
}

function Test-Cors {
    $originHeaders = @{
        Origin = $FrontendUrl
        'Access-Control-Request-Method' = 'GET'
        'Access-Control-Request-Headers' = 'authorization'
    }
    $preflight = Invoke-Probe "$PublicUrl/api/v1/workspaces" -Method Options -Headers $originHeaders -Timeout 15
    if ($null -eq $preflight -or $preflight.Status -ne 200) {
        throw "CORS preflight from $FrontendUrl did not return 200."
    }
    $allowed = Get-HeaderValue $preflight 'Access-Control-Allow-Origin'
    if ($allowed -ne $FrontendUrl) {
        throw "CORS preflight allowed '$allowed', expected '$FrontendUrl'."
    }

    $unauthorised = Invoke-Probe "$PublicUrl/api/v1/workspaces" -Headers @{ Origin = $FrontendUrl } -Timeout 15
    if ($null -eq $unauthorised -or $unauthorised.Status -ne 401) {
        throw 'A public browser-origin request to a protected route did not return 401.'
    }
    $allowed = Get-HeaderValue $unauthorised 'Access-Control-Allow-Origin'
    if ($allowed -ne $FrontendUrl) {
        throw "The protected-route response did not expose CORS access to $FrontendUrl."
    }
    Write-Log 'CORS preflight and protected-route boundary verified.'
}

function Test-Frontend {
    $page = Invoke-Probe $FrontendUrl -Timeout 20
    if ($null -eq $page -or $page.Status -ne 200) {
        throw "The deployed frontend $FrontendUrl did not return 200."
    }
    if ($page.Body -notmatch 'Aetrix') {
        throw "The response from $FrontendUrl does not look like the Aetrix frontend."
    }
    $frontendEnv = Join-Path $Root 'frontend\.env'
    $configured = ''
    foreach ($line in Get-Content $frontendEnv) {
        if ($line -match '^\s*VITE_AETRIX_API_URL\s*=\s*(.*)$') {
            $configured = $Matches[1].Trim().Trim('"').TrimEnd('/')
            break
        }
    }
    if ($Mode -in @('named', 'tailscale') -and $configured -ne $PublicUrl) {
        throw "The deployed frontend build input points at '$configured', not '$PublicUrl'. Rebuild and redeploy Pages."
    }
    if ($Mode -in @('named', 'tailscale')) {
        $expectedHost = ([uri]$PublicUrl).Host
        $scriptUrls = [regex]::Matches($page.Body, '<script[^>]+src="([^"]+)"') |
            ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
        if ($scriptUrls.Count -eq 0) { throw 'The deployed frontend did not expose any JavaScript entry point to verify.' }
        $found = $false
        foreach ($scriptUrl in $scriptUrls) {
            $assetUrl = (New-Object System.Uri([uri]$FrontendUrl, $scriptUrl)).AbsoluteUri
            $asset = Invoke-Probe $assetUrl -Timeout 20
            if ($null -eq $asset -or $asset.Status -ne 200) { continue }
            if ($asset.Body -match 'trycloudflare\.com') {
                throw "The deployed frontend still contains a quick-tunnel hostname in $assetUrl."
            }
            if ($asset.Body -match [regex]::Escape($expectedHost)) { $found = $true }
        }
        if (-not $found) {
            throw "The deployed frontend JavaScript does not contain $expectedHost. Rebuild and redeploy Pages."
        }
    }
    Write-Log "Deployed frontend reachable at $FrontendUrl and points at $PublicUrl."
}

function Get-StatusComponent([string]$Name) {
    $status = Invoke-Probe "$PublicUrl/status" -Timeout 20
    if ($null -eq $status -or $status.Status -ne 200) {
        throw "Public $PublicUrl/status did not return 200."
    }
    $payload = $status.Body | ConvertFrom-Json
    return ($payload.components | Where-Object { $_.name -eq $Name } | Select-Object -First 1)
}

function Verify-Connectivity {
    if (-not (Test-PublicHealth)) { throw "Public $PublicUrl/health is not healthy." }
    if (-not (Test-PublicReady)) { throw "Public $PublicUrl/ready did not confirm database readiness." }

    # A renewed heartbeat is the only evidence the API has that the worker
    # process is alive. Wait for it instead of trusting that the process started.
    $script:WorkerComponent = $null
    if (-not (Wait-For {
                try {
                    $component = Get-StatusComponent 'Background worker'
                    if ($null -ne $component -and $component.operational -eq 'available') {
                        $script:WorkerComponent = $component
                        return $true
                    }
                } catch { }
                return $false
            } 30 'the worker heartbeat')) {
        throw "GET /status reports no live worker heartbeat. See $WorkerLog."
    }
    Write-Log "Worker heartbeat verified: $($script:WorkerComponent.diagnostic)"

    # Provider reachability comes from a recorded live call, not a call made by
    # this check. It must not block startup: marking is unimplemented, so an
    # unverified provider is the honest state, not a reason to refuse to run.
    try {
        $provider = Get-StatusComponent 'AI provider'
        if ($null -eq $provider) {
            Write-Log 'GET /status did not report the AI provider.' 'WARN'
        } elseif ($provider.operational -eq 'available') {
            Write-Log "Gemini live response verified: $($provider.diagnostic)"
        } else {
            Write-Log "Gemini provider is $($provider.operational); mathematical correction remains unverified. $($provider.diagnostic)" 'WARN'
        }
    } catch {
        Write-Log "Provider status could not be read: $($_.Exception.Message)" 'WARN'
    }

    Test-Cors
    Test-Frontend
    Write-Log 'Connectivity verified: frontend origin, public HTTPS, CORS, backend health, database readiness and worker heartbeat.'
}

function Start-Monitor {
    Initialize-State
    foreach ($path in @($MonitorLog, $MonitorErr)) {
        if (Test-Path $path) { Move-Item $path "$path.previous" -Force }
    }
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath, 'supervise')
    $process = Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $Root `
        -RedirectStandardOutput $MonitorLog -RedirectStandardError $MonitorErr -WindowStyle Hidden -PassThru
    $script:MonitorPid = [int]$process.Id
    Save-State
    Write-Log "Supervisor started (PID $script:MonitorPid)."
}

function Add-Restart {
    $now = Get-Date
    $cutoff = $now.AddMinutes(-$RestartWindow)
    $kept = New-Object System.Collections.ArrayList
    foreach ($time in $RestartTimes) { if ($time -gt $cutoff) { [void]$kept.Add($time) } }
    [void]$kept.Add($now)
    $script:RestartTimes = $kept
    if ($kept.Count -gt $MaxRestarts) {
        throw "Restart limit reached: $($kept.Count) restarts in $RestartWindow minutes. Supervisor stopped to avoid a loop."
    }
}

function Restart-Worker {
    Add-Restart
    Write-Log 'Worker process is down; restarting.' 'WARN'
    $script:WorkerStartedByUs = $false
    Start-WorkerProcess
}

function Restart-Backend {
    Add-Restart
    Write-Log 'Backend process is down; restarting.' 'WARN'
    $script:BackendStartedByUs = $false
    Start-BackendProcess
    if (-not (Test-PublicHealth)) {
        Write-Log 'Backend restarted but the public endpoint is still down.' 'ERROR'
    } else {
        Write-Log 'Backend restarted and public /health recovered.'
    }
}

function Restart-Tunnel {
    Add-Restart
    Write-Log 'Tunnel is down; restarting.' 'WARN'
    if ($script:Mode -eq 'tailscale') { Ensure-TailscaleRunning }
    Stop-Tunnel
    $script:TunnelStartedByUs = $false
    Start-TunnelProcess
    if (-not (Test-PublicHealth)) {
        throw 'Tunnel restarted but the public endpoint did not recover.'
    }
    Write-Log 'Tunnel restarted and public /health recovered.'
}

function Invoke-Supervisor {
    Initialize-State
    $state = Get-State
    if ($null -eq $state) { Write-Log 'No stack state; supervisor exiting.' 'ERROR'; return 1 }
    $script:BackendPid = [int]$state.backendPid
    $script:WorkerPid = [int]$state.workerPid
    $script:TunnelPid = [int]$state.tunnelPid
    $script:PublicUrl = [string]$state.publicUrl
    $script:Mode = [string]$state.mode
    # Restarts inside the supervisor call Save-State; keep the supervisor's own
    # PID in that file or a later STOP cannot identify and stop it.
    $script:MonitorPid = $PID
    Save-State
    Write-Log "Supervisor active (backend $script:BackendPid, worker $script:WorkerPid, tunnel $script:TunnelPid)."
    $publicFailures = 0
    try {
        while (-not (Test-Path $StopPath)) {
            $backend = Get-ProcessRecord $script:BackendPid
            if (-not (Test-BackendProcess $backend)) {
                Restart-Backend
                $publicFailures = 0
            }
            if (-not (Test-WorkerProcess (Get-ProcessRecord $script:WorkerPid))) {
                Restart-Worker
                $publicFailures = 0
            }
            if (-not (Test-TunnelAlive)) {
                Restart-Tunnel
                $publicFailures = 0
            }

            if (Test-PublicHealth) {
                $publicFailures = 0
            } else {
                $publicFailures++
                Write-Log "Public /health failed ($publicFailures consecutive checks)." 'WARN'
                if ($publicFailures -ge 3) {
                    Restart-Tunnel
                    $publicFailures = 0
                }
            }

            if (-not (Test-LocalReady)) {
                Write-Log 'Backend is alive but database readiness is failing; not restarting backend.' 'WARN'
            }
            Start-Sleep -Seconds $Interval
        }
        Write-Log 'Stop requested; supervisor exiting.'
    } catch {
        Write-Log ("Supervisor stopped: " + $_.Exception.Message) 'ERROR'
        return 1
    }
    return 0
}

function Start-Stack {
    Initialize-State
    Write-Log "Start requested (mode $script:Mode, public $(if ($script:PublicUrl) { $script:PublicUrl } else { '(unset)' }))."
    if (Test-Path $StopPath) { Remove-Item $StopPath -Force }
    try {
        $existing = Get-State
        if ($null -ne $existing) {
            $monitor = Get-ProcessRecord ([int]$existing.monitorPid)
            if (Test-MonitorProcess $monitor) {
                Write-Log "Aetrix is already managed by supervisor PID $($existing.monitorPid)."
                $script:PublicUrl = [string]$existing.publicUrl
                $script:Mode = [string]$existing.mode
                $script:BackendPid = [int]$existing.backendPid
                $script:WorkerPid = [int]$existing.workerPid
                $script:TunnelPid = [int]$existing.tunnelPid
                $script:MonitorPid = [int]$existing.monitorPid
                Verify-Connectivity
                Write-StartSummary
                return 0
            }
        }

        if ($Mode -eq 'tailscale') { Ensure-TailscaleRunning }
        Test-Configuration
        Start-BackendProcess
        Start-WorkerProcess
        Start-TunnelProcess
        Verify-Connectivity
        Start-Monitor
        Write-StartSummary
        return 0
    } catch {
        Write-Log ("Startup failed: " + $_.Exception.Message) 'ERROR'
        if ($TunnelStartedByUs) { Stop-Tunnel }
        if ($WorkerStartedByUs) { Stop-Worker }
        if ($BackendStartedByUs) { Stop-OwnedProcess $script:BackendPid 'backend' }
        Remove-State
        return 1
    }
}

function Write-StartSummary {
    Write-Host ''
    Write-Host '[OK] Aetrix stack is running.' -ForegroundColor Green
    Write-Host "  Frontend : $FrontendUrl"
    Write-Host "  Backend  : $LocalUrl"
    Write-Host "  Worker   : running (PID $WorkerPid)"
    Write-Host "  Public   : $PublicUrl"
    if ($Mode -eq 'tailscale') { Write-Host '  Tunnel   : Tailscale Funnel' }
    Write-Host "  Supervisor PID: $MonitorPid"
    Write-Host "  Logs     : $StateDir"
    Write-Host ''
    Write-Host 'Use STATUS_AETRIX.bat to check every layer and STOP_AETRIX.bat to stop only this stack.'
}

function Stop-Stack {
    Initialize-State
    if (Test-Path $StopPath) { Remove-Item $StopPath -Force }
    $state = Get-State
    if ($null -eq $state) {
        Write-Log 'No managed stack state; checking legacy recorded processes.'
    } else {
        $script:BackendPid = [int]$state.backendPid
        $script:WorkerPid = [int]$state.workerPid
        $script:TunnelPid = [int]$state.tunnelPid
        $script:MonitorPid = [int]$state.monitorPid
        $script:Mode = [string]$state.mode
        if (-not [string]::IsNullOrWhiteSpace([string]$state.publicUrl)) { $script:PublicUrl = [string]$state.publicUrl }
        New-Item -ItemType File -Path $StopPath -Force | Out-Null
        if (Test-MonitorProcess (Get-ProcessRecord $script:MonitorPid)) {
            Write-Log 'Waiting for supervisor to stop ...'
            for ($i = 0; $i -lt 30; $i++) {
                if ($null -eq (Get-Process -Id $script:MonitorPid -ErrorAction SilentlyContinue)) { break }
                Start-Sleep -Milliseconds 500
            }
        }
        Stop-OwnedProcess $script:MonitorPid 'monitor'
        Stop-Worker
        Stop-OwnedProcess $script:BackendPid 'backend'
        Remove-State
    }

    Stop-Tunnel

    # Legacy scripts from before the supervisor used these locations.
    $legacyTunnelPid = Join-Path $Root '.tmp\aetrix\tunnel.pid'
    if (Test-Path $legacyTunnelPid) {
        $pidText = (Get-Content $legacyTunnelPid | Select-Object -First 1).Trim()
        if ($pidText -match '^\d+$') { Stop-OwnedProcess ([int]$pidText) 'tunnel' }
        Remove-Item $legacyTunnelPid -Force -ErrorAction SilentlyContinue
    }
    $legacyBackendPid = Join-Path $BackendDir '.aetrix-backend.pid'
    if (Test-Path $legacyBackendPid) {
        $pidText = (Get-Content $legacyBackendPid | Select-Object -First 1).Trim()
        if ($pidText -match '^\d+$') { Stop-OwnedProcess ([int]$pidText) 'backend' }
        Remove-Item $legacyBackendPid -Force -ErrorAction SilentlyContinue
    }

    # A stale legacy PID file can point at a launcher while the actual listener is
    # a child. Stop only exact Aetrix command lines so an unrelated service is safe.
    $orphanBackends = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { Test-BackendProcess $_ }
    foreach ($process in $orphanBackends) { Stop-OwnedProcess ([int]$process.ProcessId) 'backend' }
    $orphanWorkers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { Test-WorkerProcess $_ }
    foreach ($process in $orphanWorkers) { Stop-OwnedProcess ([int]$process.ProcessId) 'worker' }
    $orphanTunnels = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { (Test-TunnelProcess $_) -and ([string]$_.CommandLine -match '127\.0\.0\.1:8000') }
    foreach ($process in $orphanTunnels) { Stop-OwnedProcess ([int]$process.ProcessId) 'tunnel' }

    $listener = Get-ListenerPid 8000
    if ($listener -gt 0) {
        Write-Log "Port 8000 is still listening with PID $listener; it was not this stack's process." 'WARN'
        return 1
    }
    Write-Log 'Aetrix stack stopped; port 8000 is free.'
    return 0
}

function Get-Status {
    Initialize-State
    $failed = $false
    $state = Get-State
    $configured = $true
    if ($null -ne $state) {
        $script:Mode = [string]$state.mode
        if (-not [string]::IsNullOrWhiteSpace([string]$state.publicUrl)) { $script:PublicUrl = [string]$state.publicUrl }
    }
    Write-Host ''
    Write-Host 'Aetrix stack status' -ForegroundColor Cyan
    Write-Host "  project : $Root"
    Write-Host "  mode    : $Mode"

    try { Test-Configuration } catch {
        $configured = $false
        Write-Host ("  [FAIL] configuration: " + $_.Exception.Message) -ForegroundColor Red
        $failed = $true
    }
    Write-Host "  public  : $(if ($PublicUrl) { $PublicUrl } else { '(not configured)' })"
    Write-Host ''

    if ($null -eq $state) {
        Write-Host '  [WARN] No managed stack state. Start with START_AETRIX.bat.' -ForegroundColor Yellow
    } else {
        $backend = Get-ProcessRecord ([int]$state.backendPid)
        $monitor = Get-ProcessRecord ([int]$state.monitorPid)
        Write-Host ("  backend PID {0}: {1}" -f $state.backendPid, $(if (Test-BackendProcess $backend) { 'running' } else { 'not running' }))
        if ($Mode -eq 'tailscale') {
            Write-Host ("  tunnel  Tailscale Funnel: {0}" -f $(if (Test-TailscaleFunnel) { 'running' } else { 'not running' }))
        } else {
            $tunnel = Get-ProcessRecord ([int]$state.tunnelPid)
            Write-Host ("  tunnel  PID {0}: {1}" -f $state.tunnelPid, $(if (Test-TunnelProcess $tunnel) { 'running' } else { 'not running' }))
        }
        $worker = Get-ProcessRecord ([int]$state.workerPid)
        Write-Host ("  worker  PID {0}: {1}" -f $state.workerPid, $(if (Test-WorkerProcess $worker) { 'running' } else { 'not running' }))
        Write-Host ("  monitor PID {0}: {1}" -f $state.monitorPid, $(if (Test-MonitorProcess $monitor) { 'running' } else { 'not running' }))
    }

    if ($null -ne $state) {
        if (Test-WorkerProcess (Get-ProcessRecord ([int]$state.workerPid))) { Write-Host '  [PASS] worker process' -ForegroundColor Green } else { Write-Host '  [FAIL] worker process' -ForegroundColor Red; $failed = $true }
    }

    if (Test-LocalHealth) { Write-Host '  [PASS] local /health' -ForegroundColor Green } else { Write-Host '  [FAIL] local /health' -ForegroundColor Red; $failed = $true }
    if (Test-LocalReady) { Write-Host '  [PASS] local /ready (database)' -ForegroundColor Green } else { Write-Host '  [FAIL] local /ready (database)' -ForegroundColor Red; $failed = $true }

    if ($configured -and -not [string]::IsNullOrWhiteSpace($PublicUrl)) {
        if (Test-PublicHealth) { Write-Host '  [PASS] public /health' -ForegroundColor Green } else { Write-Host '  [FAIL] public /health' -ForegroundColor Red; $failed = $true }
        if (Test-PublicReady) { Write-Host '  [PASS] public /ready (database)' -ForegroundColor Green } else { Write-Host '  [FAIL] public /ready (database)' -ForegroundColor Red; $failed = $true }
        try { Test-Cors; Write-Host '  [PASS] CORS + protected-route origin' -ForegroundColor Green } catch { Write-Host ("  [FAIL] CORS: " + $_.Exception.Message) -ForegroundColor Red; $failed = $true }
        try { Test-Frontend; Write-Host '  [PASS] deployed frontend' -ForegroundColor Green } catch { Write-Host ("  [FAIL] frontend: " + $_.Exception.Message) -ForegroundColor Red; $failed = $true }
    } else {
        Write-Host '  [SKIP] public, CORS and frontend checks until a stable API origin is configured.' -ForegroundColor Yellow
    }

    Write-Host ''
    if ($failed) { Write-Host 'STATUS: NOT CONNECTED' -ForegroundColor Red; return 1 }
    Write-Host 'STATUS: CONNECTED' -ForegroundColor Green
    return 0
}

switch ($Action) {
    'start' { exit (Start-Stack) }
    'stop' { exit (Stop-Stack) }
    'restart' {
        $stopped = Stop-Stack
        if ($stopped -ne 0) { exit $stopped }
        Start-Sleep -Seconds 2
        exit (Start-Stack)
    }
    'status' { exit (Get-Status) }
    'supervise' { exit (Invoke-Supervisor) }
    default { Write-Host 'Usage: aetrix-stack.ps1 [start|stop|restart|status|supervise]'; exit 2 }
}
