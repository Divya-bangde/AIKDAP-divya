<#
.SYNOPSIS
    Sprint 10B: bring up the seminar/demo stack -- local compute + Supabase
    database + a public Cloudflare Tunnel HTTPS endpoint for the Vercel
    frontend.

.DESCRIPTION
    Target architecture:

        Vercel (public frontend)
          -> Cloudflare Tunnel (public HTTPS)
            -> FastAPI on this laptop, localhost:8001
              -> Redis / Celery / Ollama (Qwen, BGE-M3) / reranker  (local)
              -> Supabase PostgreSQL + pgvector                     (cloud)

    NOTE (Sprint 10B correction): LocalTunnel was tried first and dropped.
    Its browser-interstitial/password mechanism served an HTML page in
    place of the JSON response on real browser requests (confirmed by a
    failed live login/registration test against the deployed Vercel
    frontend), and a request-header bypass proved unreliable across the
    different request shapes the frontend makes. Cloudflare's Quick
    Tunnel (`cloudflared tunnel --url ...`) was verified to be fully
    transparent to a real browser User-Agent with zero extra headers, so
    the frontend needs no tunnel-specific code at all.

    This script does NOT deploy FastAPI anywhere. The laptop is the seminar
    compute server, intentionally. It only:
      1. checks Docker Desktop is running
      2. verifies Ollama is reachable and has the required models
      3. starts the BGE-Reranker-v2-m3 server if it isn't already up
         (delegates to scripts/reranker.ps1 -- no duplicate logic)
      4. points the `backend` + `worker` containers at Supabase for this
         run only, by swapping DATABASE_URL / BACKEND_CORS_ORIGINS in
         `.env` (root .env is the single source those containers read via
         `env_file:` in docker-compose.yml -- that's the existing,
         frozen architecture, so this script works with it rather than
         inventing a second config path). The previous `.env` is backed
         up first and `-Stop` restores it -- nothing here is permanent.
      5. restarts backend + worker so they pick up the new DATABASE_URL
      6. starts a Cloudflare Quick Tunnel on port 8001 ONLY (never the
         database, Redis, Ollama, or the reranker port) and prints the
         assigned public URL
      7. reminds the operator to update Vercel's VITE_API_BASE_URL and
         redeploy -- this script cannot do that step; it has no Vercel
         session

    QUICK TUNNEL URLS ARE NOT STABLE. A fresh `-Start` gets a new
    "*.trycloudflare.com" hostname every time -- Quick Tunnels have no
    concept of a reserved name (that requires a named tunnel bound to a
    Cloudflare account/zone, out of scope for this seminar setup). Re-run
    `-Start` and re-check the printed URL before every seminar; do not
    assume yesterday's URL still works.

    SPRINT 11: -Watch adds an optional supervisor that keeps running
    after startup instead of exiting. It periodically checks the tunnel
    through its own public URL (not just "is the process alive" -- a
    Quick Tunnel's control-stream connection to Cloudflare's edge can
    die while the local `cloudflared` process keeps running, which is
    exactly what happened during Sprint 11's investigation and is
    invisible to a process-liveness check alone). On a confirmed dead
    tunnel it restarts `cloudflared`, extracts the new URL with the same
    parsing `Start-CloudflareTunnel` already uses, and -- only if
    -VercelToken/-VercelProjectId are configured -- pushes the new URL
    to Vercel's Production VITE_API_BASE_URL and triggers a redeploy via
    a Deploy Hook. Without those, Watch mode still recovers the tunnel;
    it just logs that you need to update Vercel yourself, exactly as the
    non-Watch path already requires today.

.EXAMPLE
    # Seminar day, hands-off (recommended): start everything and keep
    # watching/recovering the tunnel + syncing Vercel until Ctrl+C:
    .\scripts\seminar-start.ps1 -Start -Watch `
        -SupabaseDatabaseUrl "postgresql+psycopg://postgres.<ref>:<pw>@aws-<region>.pooler.supabase.com:5432/postgres?sslmode=require" `
        -VercelOrigin "https://<your-project>.vercel.app"
    # (-VercelToken / -VercelProjectId / -VercelDeployHookUrl default to
    # $env:AIKDAP_VERCEL_TOKEN / $env:AIKDAP_VERCEL_PROJECT_ID /
    # $env:AIKDAP_VERCEL_DEPLOY_HOOK_URL -- set those once per shell
    # session rather than passing secrets on the command line.)

    # Seminar day, original one-shot behavior (unchanged):
    .\scripts\seminar-start.ps1 -Start -SupabaseDatabaseUrl "postgresql+psycopg://postgres.<ref>:<pw>@aws-<region>.pooler.supabase.com:5432/postgres?sslmode=require" -VercelOrigin "https://<your-project>.vercel.app"

    # Check what's up:
    .\scripts\seminar-start.ps1 -Status

    # After the seminar, return to normal local development:
    .\scripts\seminar-start.ps1 -Stop
#>
[CmdletBinding(DefaultParameterSetName = 'Status')]
param(
    [Parameter(ParameterSetName = 'Start', Mandatory = $true)]
    [switch]$Start,

    [Parameter(ParameterSetName = 'Stop', Mandatory = $true)]
    [switch]$Stop,

    [Parameter(ParameterSetName = 'Status')]
    [switch]$Status,

    # Supabase Session Pooler URL. Never hardcode this in the script or
    # commit it -- pass it on the command line or via an env var each time.
    [Parameter(ParameterSetName = 'Start')]
    [string]$SupabaseDatabaseUrl = $env:AIKDAP_SEMINAR_DATABASE_URL,

    # The real, currently-deployed Vercel origin (no trailing slash,
    # no /api/v1). Added to BACKEND_CORS_ORIGINS alongside the local
    # dev origin -- never wildcarded.
    [Parameter(ParameterSetName = 'Start')]
    [string]$VercelOrigin,

    [Parameter(ParameterSetName = 'Start')]
    [int]$FastApiPort = 8001,

    # Full path to cloudflared.exe. Defaults to the winget install
    # location; override if it's installed elsewhere or once it's on PATH.
    [Parameter(ParameterSetName = 'Start')]
    [Parameter(ParameterSetName = 'Status')]
    [string]$CloudflaredPath = 'C:\Program Files (x86)\cloudflared\cloudflared.exe',

    # Sprint 11: keep running after startup, supervising the tunnel and
    # auto-recovering it instead of exiting once. Ctrl+C to stop.
    [Parameter(ParameterSetName = 'Start')]
    [switch]$Watch,

    # How often the supervisor checks <tunnel>/health.
    [Parameter(ParameterSetName = 'Start')]
    [int]$WatchIntervalSeconds = 30,

    # Consecutive failed checks required before the tunnel is declared
    # dead and restarted. >1 on purpose -- a single failed check is
    # ordinary network jitter, not evidence the tunnel is actually down.
    [Parameter(ParameterSetName = 'Start')]
    [int]$WatchFailureThreshold = 3,

    # Vercel Personal Access Token (Account Settings -> Tokens). Only
    # used to look up and PATCH the Production VITE_API_BASE_URL env
    # var. Never logged, never written to a file, never hardcoded here --
    # same convention as -SupabaseDatabaseUrl above: pass it or set the
    # env var, this script never invents or persists it.
    [Parameter(ParameterSetName = 'Start')]
    [string]$VercelToken = $env:AIKDAP_VERCEL_TOKEN,

    # Vercel project ID or name (Project Settings -> General). Not a
    # secret, but still not hardcoded -- it's project-specific and this
    # script is meant to work for any AIKDAP checkout.
    [Parameter(ParameterSetName = 'Start')]
    [string]$VercelProjectId = $env:AIKDAP_VERCEL_PROJECT_ID,

    # Deploy Hook URL (Project Settings -> Git -> Deploy Hooks, pick the
    # production branch). Vercel's own docs treat this URL itself as a
    # sensitive credential -- anyone with it can trigger a deploy -- so
    # it gets the same never-logged treatment as -VercelToken.
    [Parameter(ParameterSetName = 'Start')]
    [string]$VercelDeployHookUrl = $env:AIKDAP_VERCEL_DEPLOY_HOOK_URL
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $repoRoot '.env'

function Resolve-Cloudflared {
    if (Test-Path $CloudflaredPath) { return $CloudflaredPath }
    $onPath = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    throw "cloudflared.exe not found at '$CloudflaredPath' and not on PATH. Install with: winget install --id Cloudflare.cloudflared -e"
}

function Test-DockerRunning {
    try { docker info *> $null; return $true } catch { return $false }
}

function Test-OllamaReady {
    try {
        $resp = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 5
        $names = $resp.models | ForEach-Object { $_.name }
        $hasQwen = $names -match 'qwen3\.5'
        $hasBge = $names -match 'bge-m3'
        return [pscustomobject]@{ Reachable = $true; HasQwen = [bool]$hasQwen; HasBge = [bool]$hasBge }
    } catch {
        return [pscustomobject]@{ Reachable = $false; HasQwen = $false; HasBge = $false }
    }
}

function Wait-BackendHealth {
    param([int]$Port = 8001, [int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $health = Get-BackendHealth -Port $Port
        if ($health) { return $health }
        Start-Sleep -Seconds 2
    }
    return $null
}

function Get-BackendHealth {
    param([int]$Port = 8001)
    try { return Invoke-RestMethod -Uri "http://localhost:$Port/health" -TimeoutSec 5 } catch { return $null }
}

function Write-SupervisorLog {
    # Timestamped event log for -Watch, written to console AND a log
    # file (so a demo-day failure has a paper trail afterward, not just
    # whatever scrolled off the terminal). NEVER pass a secret value
    # (token, deploy hook URL) to this function -- callers below only
    # ever log facts (URLs, counts, outcomes), never credentials.
    param([string]$Message)
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Output $line
    $logFile = Join-Path $env:TEMP 'aikdap-supervisor.log'
    Add-Content -Path $logFile -Value $line
}

function Start-CloudflareTunnel {
    # Starts a fresh Quick Tunnel and returns @{ Url = ...; Process = ... }
    # once verified reachable. Shared by both the initial `-Start` path
    # and the -Watch supervisor's recovery path, so there is exactly one
    # place that knows how to start/parse/verify a tunnel.
    param([int]$Port = 8001)

    $cloudflared = Resolve-Cloudflared
    $cfArgs = @('tunnel', '--url', "http://localhost:$Port")
    # Sprint 11: a unique filename per attempt, not a fixed shared path.
    # A prior cloudflared process (e.g. one -Watch is about to replace,
    # or an already-abandoned attempt) can still hold a fixed path open
    # for a moment after Stop-Process returns, which would make this
    # Remove-Item throw -- and worse, if swallowed, a still-running old
    # process appending to the same shared file could make the URL
    # regex below match its stale URL instead of the new one. A unique
    # name removes the collision entirely rather than papering over it.
    $logFile = Join-Path $env:TEMP "aikdap-cloudflared-$([guid]::NewGuid().ToString('N').Substring(0, 8)).log"

    $proc = $null
    $succeeded = $false
    try {
        # cloudflared logs its startup banner (including the assigned
        # URL) to stderr, not stdout.
        $proc = Start-Process -FilePath $cloudflared -ArgumentList $cfArgs -RedirectStandardError $logFile -WindowStyle Hidden -PassThru
        $deadline = (Get-Date).AddSeconds(30)
        $tunnelUrl = $null
        while ((Get-Date) -lt $deadline -and -not $tunnelUrl) {
            Start-Sleep -Seconds 1
            if (Test-Path $logFile) {
                $line = Get-Content $logFile | Select-String 'https://\S+\.trycloudflare\.com'
                if ($line) { $tunnelUrl = $line.Matches[0].Value }
            }
        }
        if (-not $tunnelUrl) { throw "cloudflared did not report a URL within 30s -- check $logFile" }

        # Sprint 11: a fresh Quick Tunnel hostname can take a few seconds
        # past its own banner before Cloudflare's edge actually resolves
        # it (cloudflared's own startup message says as much: "it may
        # take some time to be reachable") -- confirmed live during this
        # sprint's testing, where a flat 3s wait + single attempt
        # intermittently hit a DNS-not-ready error on a genuinely-fine
        # new tunnel. Retrying briefly here avoids treating that as a
        # hard failure. Occasionally a Quick Tunnel fails to register at
        # all within this window -- Cloudflare's own "no uptime
        # guarantee" applies to registration too, not just staying up --
        # and that's a real failure this loop correctly gives up on.
        $verifyDeadline = (Get-Date).AddSeconds(15)
        $tunnelHealth = $null
        $lastError = $null
        while ((Get-Date) -lt $verifyDeadline -and -not $tunnelHealth) {
            Start-Sleep -Seconds 2
            try {
                $tunnelHealth = Invoke-RestMethod -Uri "$tunnelUrl/health" -TimeoutSec 8
            } catch {
                $lastError = $_
            }
        }

        if (-not $tunnelHealth) {
            throw "tunnel did not become reachable within 15s of DNS propagation: $($lastError.Exception.Message)"
        }
        if ($tunnelHealth.services.postgres.status -ne 'healthy') {
            throw 'tunnel reachable but backend/postgres unhealthy through it'
        }

        $succeeded = $true
        return [pscustomobject]@{ Url = $tunnelUrl; Process = $proc }
    } finally {
        # Runs on an explicit throw above AND on external interruption
        # (Ctrl+C / Stop-Job during -Watch's recovery attempt) alike --
        # a `finally` unwinds on any scope exit, not just a `throw`. If
        # this call is leaving without a verified success, whatever
        # process it started must not survive it.
        if (-not $succeeded -and $proc) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-TunnelHealthy {
    # A short, loop-friendly liveness check -- distinct from
    # Start-CloudflareTunnel's one-time post-start verification, which
    # can afford a longer timeout because it only runs once.
    param([string]$TunnelUrl)
    try {
        $resp = Invoke-RestMethod -Uri "$TunnelUrl/health" -TimeoutSec 8
        return [bool]$resp.status
    } catch {
        return $false
    }
}

function Sync-VercelBackendUrl {
    # Pushes a new tunnel origin to Vercel's Production VITE_API_BASE_URL
    # and triggers a redeploy. Does nothing (loudly, not silently) if
    # -VercelToken/-VercelProjectId aren't configured -- the existing
    # manual workflow (update the dashboard yourself) keeps working
    # exactly as it does today.
    #
    # SECRET HANDLING: $Token is only ever used inside the Authorization
    # header of these two API calls. It is never written to
    # Write-SupervisorLog, never interpolated into a log string, never
    # persisted to a file. $DeployHookUrl gets the same treatment --
    # Vercel's own docs call it as sensitive as a credential.
    param(
        [Parameter(Mandatory = $true)][string]$NewUrl,
        [string]$Token,
        [string]$ProjectId,
        [string]$DeployHookUrl
    )

    if (-not $Token -or -not $ProjectId) {
        Write-SupervisorLog 'Vercel token/project ID not configured -- automatic sync unavailable.'
        Write-SupervisorLog "ACTION NEEDED: manually set Vercel Production VITE_API_BASE_URL to $NewUrl and redeploy."
        return
    }

    Write-SupervisorLog 'Updating Vercel Production environment'
    $headers = @{ Authorization = "Bearer $Token" }

    $envList = Invoke-RestMethod -Uri "https://api.vercel.com/v10/projects/$ProjectId/env" -Headers $headers -Method Get
    $existing = $envList.envs | Where-Object { $_.key -eq 'VITE_API_BASE_URL' -and $_.target -contains 'production' } | Select-Object -First 1
    if (-not $existing) {
        throw 'VITE_API_BASE_URL not found among Production env vars for this project -- create it once manually in the Vercel dashboard first, then Watch mode can keep it updated.'
    }

    $body = @{ value = $NewUrl } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "https://api.vercel.com/v9/projects/$ProjectId/env/$($existing.id)" -Headers $headers -Method Patch -ContentType 'application/json' -Body $body | Out-Null

    if ($DeployHookUrl) {
        Invoke-RestMethod -Uri $DeployHookUrl -Method Post | Out-Null
        Write-SupervisorLog 'Vercel redeploy triggered'
    } else {
        Write-SupervisorLog 'No Deploy Hook configured (-VercelDeployHookUrl) -- env var updated but redeploy NOT triggered. Redeploy manually.'
    }
}

function Start-TunnelSupervisor {
    param(
        [Parameter(Mandatory = $true)][string]$InitialUrl,
        [Parameter(Mandatory = $true)]$InitialProcess,
        [int]$Port = 8001,
        [int]$IntervalSeconds = 30,
        [int]$FailureThreshold = 3,
        [string]$VercelToken,
        [string]$VercelProjectId,
        [string]$VercelDeployHookUrl
    )

    $currentUrl = $InitialUrl
    $currentProc = $InitialProcess
    $consecutiveFailures = 0

    Write-SupervisorLog "Watch mode started (interval ${IntervalSeconds}s, failure threshold $FailureThreshold). Ctrl+C to stop."
    Write-SupervisorLog "Tunnel healthy: $currentUrl"

    try {
        while ($true) {
            Start-Sleep -Seconds $IntervalSeconds

            # Case 1: the process itself is gone -- unambiguous, no need
            # to wait out the failure threshold.
            $stillRunning = Get-Process -Id $currentProc.Id -ErrorAction SilentlyContinue
            $healthy = $false
            if ($stillRunning) {
                $healthy = Test-TunnelHealthy -TunnelUrl $currentUrl
            }

            if ($healthy) {
                if ($consecutiveFailures -gt 0) { Write-SupervisorLog 'Tunnel healthy' }
                $consecutiveFailures = 0
                continue
            }

            if (-not $stillRunning) {
                Write-SupervisorLog 'cloudflared process has exited'
            } else {
                $consecutiveFailures++
                Write-SupervisorLog "Tunnel health check failed ($consecutiveFailures/$FailureThreshold)"
                if ($consecutiveFailures -lt $FailureThreshold) { continue }
            }

            # Confirmed dead: process exited, OR FailureThreshold
            # consecutive checks failed while it was still running (the
            # exact "cloudflared alive, tunnel dead" case from the
            # Sprint 11 investigation).
            Write-SupervisorLog 'Restarting Cloudflare tunnel'
            if ($stillRunning) {
                Stop-Process -Id $currentProc.Id -Force -ErrorAction SilentlyContinue
            }

            $recovered = $null
            try {
                $recovered = Start-CloudflareTunnel -Port $Port
            } catch {
                Write-SupervisorLog "Tunnel restart failed: $($_.Exception.Message) -- will retry next interval"
                $consecutiveFailures = 0
                continue
            }

            Write-SupervisorLog "New tunnel URL detected: $($recovered.Url)"
            Write-SupervisorLog 'New tunnel verified'

            if ($recovered.Url -ne $currentUrl) {
                Sync-VercelBackendUrl -NewUrl $recovered.Url -Token $VercelToken -ProjectId $VercelProjectId -DeployHookUrl $VercelDeployHookUrl
            }

            $currentUrl = $recovered.Url
            $currentProc = $recovered.Process
            $consecutiveFailures = 0
            Write-SupervisorLog 'Recovery complete'
        }
    } finally {
        # Only stop the cloudflared process THIS supervisor is currently
        # tracking -- never a blanket `Get-Process cloudflared`, which
        # could belong to something else on the machine.
        $stillRunning = Get-Process -Id $currentProc.Id -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Write-SupervisorLog "Stopping supervised cloudflared (pid $($currentProc.Id))"
            Stop-Process -Id $currentProc.Id -Force -ErrorAction SilentlyContinue
        }
        Write-SupervisorLog 'Watch mode stopped'
    }
}

function Backup-EnvFile {
    if (-not (Test-Path $envPath)) { throw "root .env not found at $envPath" }
    $backup = "$envPath.seminar-backup"
    if (Test-Path $backup) {
        Write-Output "  (a previous backup already exists at $backup -- not overwriting it, since it may be the real pre-seminar local config)"
    } else {
        Copy-Item $envPath $backup
        Write-Output "  backed up current .env -> $backup"
    }
}

function Set-EnvValue {
    param([string]$Key, [string]$Value)
    $content = Get-Content $envPath
    $pattern = "^$Key="
    if ($content -match $pattern) {
        $content = $content -replace "$pattern.*", "$Key=$Value"
    } else {
        $content += "$Key=$Value"
    }
    Set-Content -Path $envPath -Value $content -Encoding utf8
}

function Start-Seminar {
    Write-Output '=== Sprint 10B seminar startup ==='

    if (-not $SupabaseDatabaseUrl) {
        throw 'Pass -SupabaseDatabaseUrl (or set $env:AIKDAP_SEMINAR_DATABASE_URL). Refusing to guess or reuse a stale credential.'
    }
    if (-not $VercelOrigin) {
        throw 'Pass -VercelOrigin with the real, currently-deployed Vercel URL (e.g. https://your-project.vercel.app). Refusing to invent one.'
    }

    Write-Output '[1/7] Docker Desktop...'
    if (-not (Test-DockerRunning)) { throw 'Docker is not running. Start Docker Desktop first.' }
    Write-Output '  ok'

    Write-Output '[2/7] Ollama (Qwen 3.5 + BGE-M3)...'
    $ollama = Test-OllamaReady
    if (-not $ollama.Reachable) { throw 'Ollama is not reachable on localhost:11434. Run "ollama serve" first.' }
    if (-not $ollama.HasQwen) { Write-Warning '  qwen3.5 model not found in `ollama list` -- document upload/synthesis via Qwen will fail.' }
    if (-not $ollama.HasBge) { Write-Warning '  bge-m3 model not found in `ollama list` -- embeddings will fail.' }
    Write-Output '  ok'

    Write-Output '[3/7] BGE-Reranker-v2-m3...'
    & (Join-Path $PSScriptRoot 'reranker.ps1') start
    Write-Output '  ok'

    Write-Output '[4/7] Pointing backend + worker at Supabase for this run...'
    Backup-EnvFile
    $corsValue = "http://localhost:5173,$VercelOrigin"
    Set-EnvValue -Key 'DATABASE_URL' -Value $SupabaseDatabaseUrl
    Set-EnvValue -Key 'BACKEND_CORS_ORIGINS' -Value $corsValue
    Write-Output "  DATABASE_URL -> Supabase Session Pooler (value not printed)"
    Write-Output "  BACKEND_CORS_ORIGINS -> $corsValue"

    Write-Output '[5/7] Restarting backend + worker (Redis/Postgres containers untouched)...'
    Push-Location $repoRoot
    try {
        docker compose up -d --force-recreate backend worker | Out-Null
    } finally {
        Pop-Location
    }
    $health = Wait-BackendHealth -Port $FastApiPort -TimeoutSeconds 40
    if (-not $health) { throw "backend did not come up healthy on port $FastApiPort within 40s of restart" }
    if ($health.services.postgres.status -ne 'healthy') {
        throw "postgres check failed against Supabase: $($health.services.postgres | ConvertTo-Json -Compress)"
    }
    Write-Output "  ok (postgres: $($health.services.postgres.status), reranker: $($health.services.reranker.status))"

    Write-Output '[6/7] Starting Cloudflare Quick Tunnel on FastAPI port only...'
    $tunnel = Start-CloudflareTunnel -Port $FastApiPort
    Write-Output "  tunnel pid $($tunnel.Process.Id): $($tunnel.Url)"

    Write-Output '[7/7] Verified the tunnel actually reaches FastAPI.'
    Write-Output '  ok'

    Write-Output ''
    Write-Output '=== READY ==='
    Write-Output "Public API URL: $($tunnel.Url)"
    Write-Output ''

    if ($Watch) {
        if ($VercelToken -and $VercelProjectId) {
            Write-Output 'Watch mode: tunnel + Vercel sync will be kept up automatically. Ctrl+C to stop.'
        } else {
            Write-Output 'Watch mode: tunnel will be kept up automatically, but Vercel sync is OFF'
            Write-Output '  (set $env:AIKDAP_VERCEL_TOKEN and $env:AIKDAP_VERCEL_PROJECT_ID to enable it).'
            Write-Output "  Until then, update Vercel's Production VITE_API_BASE_URL yourself whenever the URL above changes."
        }
        Write-Output ''
        Start-TunnelSupervisor -InitialUrl $tunnel.Url -InitialProcess $tunnel.Process -Port $FastApiPort `
            -IntervalSeconds $WatchIntervalSeconds -FailureThreshold $WatchFailureThreshold `
            -VercelToken $VercelToken -VercelProjectId $VercelProjectId -VercelDeployHookUrl $VercelDeployHookUrl
        return
    }

    Write-Output 'Next (manual -- this script has no Vercel session unless you also pass -Watch):'
    Write-Output "  1. vercel env rm VITE_API_BASE_URL production   (if one is already set)"
    Write-Output "  2. echo $($tunnel.Url) | vercel env add VITE_API_BASE_URL production"
    Write-Output '  3. vercel --prod                                  (redeploy so the build picks up the new value)'
    Write-Output "  4. Open $VercelOrigin and confirm login works end to end."
    Write-Output ''
    Write-Output 'When the seminar is over, run: .\scripts\seminar-start.ps1 -Stop'
    Write-Output 'To keep the tunnel supervised and auto-recovering instead of a one-shot start, re-run with -Watch.'
}

function Stop-Seminar {
    Write-Output '=== Restoring normal local development ==='

    Write-Output '[1/2] Stopping Cloudflare Tunnel...'
    Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Output '  ok'

    Write-Output '[2/2] Restoring .env and restarting backend + worker on local Postgres...'
    $backup = "$envPath.seminar-backup"
    if (Test-Path $backup) {
        Copy-Item $backup $envPath -Force
        Write-Output "  restored .env from $backup"
    } else {
        Write-Warning '  no .env.seminar-backup found -- .env left as-is. Verify DATABASE_URL manually.'
    }
    Push-Location $repoRoot
    try {
        docker compose up -d --force-recreate backend worker | Out-Null
    } finally {
        Pop-Location
    }
    $health = Wait-BackendHealth -TimeoutSeconds 40
    if ($health) {
        Write-Output "  local backend health: postgres=$($health.services.postgres.status)"
    } else {
        Write-Warning '  backend did not respond after restart -- check `docker compose logs backend`.'
    }
}

function Show-Status {
    Write-Output '=== Seminar stack status ==='
    Write-Output "Docker: $(if (Test-DockerRunning) { 'running' } else { 'NOT running' })"
    $ollama = Test-OllamaReady
    Write-Output "Ollama: $(if ($ollama.Reachable) { 'reachable' } else { 'NOT reachable' }) (qwen3.5: $($ollama.HasQwen), bge-m3: $($ollama.HasBge))"
    & (Join-Path $PSScriptRoot 'reranker.ps1') status
    $health = Get-BackendHealth
    if ($health) {
        Write-Output "FastAPI (localhost:8001): $($health.status) (postgres: $($health.services.postgres.status))"
    } else {
        Write-Output 'FastAPI (localhost:8001): NOT responding'
    }
    $cfProc = Get-Process cloudflared -ErrorAction SilentlyContinue
    Write-Output "Cloudflare Tunnel process: $(if ($cfProc) { "running (pid $($cfProc.Id))" } else { 'not running' })"
}

switch ($PSCmdlet.ParameterSetName) {
    'Start' { Start-Seminar }
    'Stop' { Stop-Seminar }
    default { Show-Status }
}
