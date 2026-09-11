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
    .\scripts\reranker.ps1 register     # auto-start at logon, restart on crash
    .\scripts\reranker.ps1 unregister
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'status', 'register', 'unregister')]
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
$taskName = 'AIKDAP Reranker'

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

function Get-RerankerTask {
    Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
}

function Assert-RerankerFiles {
    foreach ($path in @($binary, $model)) {
        if (-not (Test-Path $path)) { throw "missing: $path" }
    }
}

function Get-RerankerArguments {
    # -ngl 99 offloads every layer; the model is ~606 MiB at Q8_0 and
    # uses roughly 431 MiB of VRAM resident, so it coexists with BGE-M3
    # on an 8 GB card. --pooling rank is required: this GGUF does not
    # declare a default pooling type, and a reranker needs rank pooling.
    '-m "{0}" --host 0.0.0.0 --port {1} --reranking --pooling rank -ngl 99 --ctx-size 8192' `
        -f $model, $RerankerPort
}

function Start-Reranker {
    if (Get-RerankerProcess) { Write-Output 'already running'; return }
    Assert-RerankerFiles

    if (Get-RerankerTask) {
        # Registered: start through Task Scheduler so it owns the process
        # and its restart-on-crash policy applies to this run too.
        Start-ScheduledTask -TaskName $taskName
    } else {
        Start-Process -FilePath $binary -ArgumentList (Get-RerankerArguments) `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden
    }

    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Date) -lt $deadline) {
        if (Test-RerankerHealth) { Write-Output "started on port $RerankerPort"; return }
        Start-Sleep -Seconds 2
    }
    throw "did not become healthy within 60s; see $stderr"
}

function Stop-Reranker {
    # Stop the task first: that ends the host's restart loop. Killing
    # only llama-server would just be restarted by the loop 5s later.
    if (Get-RerankerTask) { Stop-ScheduledTask -TaskName $taskName }
    $process = Get-RerankerProcess
    if (-not $process) { Write-Output 'not running'; return }
    $process | Stop-Process -Force
    Write-Output 'stopped'
}

function Register-Reranker {
    Assert-RerankerFiles

    # WHY SUPERVISED
    # Start-Process leaves a detached process nothing watches. On
    # 2026-09-02 it stopped and stayed down for 8 days, with retrieval
    # silently degraded to stage-1 order the whole time.
    #
    # The restart loop lives in the hidden PowerShell host, not in Task
    # Scheduler: its restart-on-failure only covers an action that fails
    # to *launch*, not a later non-zero exit -- verified: a killed
    # llama-server stayed down for 150s under that policy alone. Task
    # Scheduler supplies the logon start, and restarts the host itself if
    # the host dies. The 5s pause keeps a persistent failure (missing
    # model, port taken) from spinning. -EncodedCommand sidesteps quoting
    # the space in the user-profile path.
    $command = "while (`$true) { & '$binary' $(Get-RerankerArguments) --log-file '$stderr'; Start-Sleep -Seconds 5 }"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -WindowStyle Hidden -EncodedCommand $encoded"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $taskSettings = New-ScheduledTaskSettingsSet -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Settings $taskSettings -Force `
        -Description 'AIKDAP stage-2 reranker (llama-server, BGE-Reranker-v2-m3). Managed by scripts/reranker.ps1.' |
        Out-Null
    Write-Output "registered '$taskName': starts at logon, restarts within seconds of a crash"
}

function Unregister-Reranker {
    if (-not (Get-RerankerTask)) { Write-Output 'not registered'; return }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "unregistered '$taskName'"
}

switch ($Action) {
    'start' { Start-Reranker }
    'stop' { Stop-Reranker }
    'restart' { Stop-Reranker; Start-Sleep -Seconds 2; Start-Reranker }
    'register' { Register-Reranker }
    'unregister' { Unregister-Reranker }
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
        $task = Get-RerankerTask
        $supervision = if ($task) { "supervised by task '$taskName' ($($task.State))" } else { 'NOT supervised (run: reranker.ps1 register)' }
        Write-Output "  $supervision"
    }
}
