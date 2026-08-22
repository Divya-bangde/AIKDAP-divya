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

.EXAMPLE
    # Seminar day:
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
    [string]$CloudflaredPath = 'C:\Program Files (x86)\cloudflared\cloudflared.exe'
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
    $cloudflared = Resolve-Cloudflared
    $cfArgs = @('tunnel', '--url', "http://localhost:$FastApiPort")
    $logFile = Join-Path $env:TEMP 'aikdap-cloudflared.log'
    if (Test-Path $logFile) { Remove-Item $logFile -Force }
    # cloudflared logs its startup banner (including the assigned URL) to
    # stderr, not stdout.
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
    Write-Output "  tunnel pid $($proc.Id): $tunnelUrl"

    Write-Output '[7/7] Verifying the tunnel actually reaches FastAPI...'
    Start-Sleep -Seconds 3
    $tunnelHealth = Invoke-RestMethod -Uri "$tunnelUrl/health" -TimeoutSec 20
    if ($tunnelHealth.services.postgres.status -ne 'healthy') { throw 'tunnel reachable but backend/postgres unhealthy through it' }
    Write-Output '  ok'

    Write-Output ''
    Write-Output '=== READY ==='
    Write-Output "Public API URL: $tunnelUrl"
    Write-Output ''
    Write-Output 'Next (manual -- this script has no Vercel session):'
    Write-Output "  1. vercel env rm VITE_API_BASE_URL production   (if one is already set)"
    Write-Output "  2. echo $tunnelUrl | vercel env add VITE_API_BASE_URL production"
    Write-Output '  3. vercel --prod                                  (redeploy so the build picks up the new value)'
    Write-Output "  4. Open $VercelOrigin and confirm login works end to end."
    Write-Output ''
    Write-Output 'When the seminar is over, run: .\scripts\seminar-start.ps1 -Stop'
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
