<#
.SYNOPSIS
    Start, stop, or check the BGE-Reranker-v2-m3 server (stage 2 of AIKDAP retrieval).

.DESCRIPTION
    Stage 2 of two-stage retrieval runs BAAI/bge-reranker-v2-m3 under
    llama.cpp's `llama-server --reranking`. It is a separate process
    from Ollama, which still serves BGE-M3 (stage 1) and Qwen.

    WHY NOT A DOCKER COMPOSE SERVICE
    Ollama cannot serve this model at all: it exposes no rerank
    endpoint, reports the model's only capability as `completion`, and
    crashes its llama-server subprocess (exit 0xc0000409) on both
    /api/embed and /api/generate. llama.cpp can, but containerising it
    with CUDA on Docker Desktop for Windows would mean GPU passthrough
    into WSL2 plus a multi-gigabyte CUDA base image, to reach the same
    GPU this host process already uses directly. Per the "simplest
    reliable architecture" rule, it runs on the host and the containers
    reach it through host.docker.internal.

    BINDING
    Binds 0.0.0.0 because Docker Desktop containers reach the host via
    a virtual gateway, not loopback -- 127.0.0.1 would be unreachable
    from the backend container. The port is not forwarded anywhere, so
    exposure is limited to this machine and its containers. Do not
    forward RerankerPort through a router or firewall.

.EXAMPLE
    .\scripts\reranker.ps1 start
    .\scripts\reranker.ps1 status
    .\scripts\reranker.ps1 stop
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status')]
    [string]$Action = 'status',

    # Must match RERANKER_BASE_URL in .env.
    [int]$RerankerPort = 8090,

    [string]$Root = "$env:LOCALAPPDATA\llama.cpp"
)

$ErrorActionPreference = 'Stop'

$binary = Join-Path $Root 'bin\llama-server.exe'
$model = Join-Path $Root 'models\bge-reranker-v2-m3-Q8_0.gguf'
$stdout = Join-Path $Root 'reranker.log'
$stderr = Join-Path $Root 'reranker.err.log'

function Get-RerankerProcess {
    Get-Process llama-server -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $binary }
}

function Test-RerankerHealth {
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:$RerankerPort/health" `
            -UseBasicParsing -TimeoutSec 5
        return $true
    } catch {
        return $false
    }
}

function Start-Reranker {
    if (Get-RerankerProcess) { Write-Output 'already running'; return }
    foreach ($path in @($binary, $model)) {
        if (-not (Test-Path $path)) { throw "missing: $path" }
    }

    # -ngl 99 offloads every layer; the model is ~606 MiB at Q8_0 and
    # uses roughly 431 MiB of VRAM resident, so it coexists with BGE-M3
    # on an 8 GB card. --pooling rank is required: this GGUF does not
    # declare a default pooling type, and a reranker needs rank pooling.
    $argline = '-m "{0}" --host 0.0.0.0 --port {1} --reranking --pooling rank -ngl 99 --ctx-size 8192' `
        -f $model, $RerankerPort
    Start-Process -FilePath $binary -ArgumentList $argline `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-RerankerHealth) { Write-Output "started on port $RerankerPort"; return }
        Start-Sleep -Seconds 2
    }
    throw "did not become healthy within 60s; see $stderr"
}

function Stop-Reranker {
    $process = Get-RerankerProcess
    if (-not $process) { Write-Output 'not running'; return }
    $process | Stop-Process -Force
    Write-Output 'stopped'
}

switch ($Action) {
    'start' { Start-Reranker }
    'stop' { Stop-Reranker }
    'restart' { Stop-Reranker; Start-Sleep -Seconds 2; Start-Reranker }
    'status' {
        $process = Get-RerankerProcess
        if (-not $process) {
            Write-Output 'reranker: NOT RUNNING'
            # Not fatal for the application: retrieval degrades to
            # stage 1 and reports reranking_status=unavailable.
            Write-Output '  (semantic search will report reranking_status=unavailable)'
        } else {
            $healthy = if (Test-RerankerHealth) { 'healthy' } else { 'not answering' }
            Write-Output "reranker: RUNNING (pid $($process.Id), port $RerankerPort, $healthy)"
        }
    }
}
