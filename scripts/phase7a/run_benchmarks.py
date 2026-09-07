"""Sprint 16 Phase 7A -- disposable Docker container runtime benchmark.

BENCHMARK-ONLY INFRASTRUCTURE. Not part of the application. Does not
implement experiment execution, does not run user/LLM-generated code,
does not create any production endpoint, worker, or migration.

Runs entirely from the host (via `docker` CLI subprocess calls) against
disposable, network-isolated, non-privileged containers using only
stock public images (`alpine:3.19`, `python:3.12-slim`) and synthetic
workloads (CPU spin, memory allocation, sleep, bounded stdout, a small
bounded number of child sleep processes, a small bounded file write).
No application source, `.env`, host filesystem, or Docker socket is
ever mounted into a benchmark container. No project/user data is used.

Writes machine-readable results to `results.json` next to this file.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

RESULTS: dict = {
    "benchmark_suite": "sprint16-phase7a-container-runtime",
    "generated_at": None,
    "docker_version": None,
    "host_context": None,
    "parts": {},
}

ALPINE_IMAGE = "alpine:3.19"
PYTHON_IMAGE = "python:3.12-slim"

# Real, verified env var NAMES (never values) from this project's root
# .env, used only to confirm their ABSENCE inside a benchmark
# container's environment (Part E).
KNOWN_SECRET_ENV_NAMES = [
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "DATABASE_URL",
    "CELERY_BROKER_URL",
    "CELERY_RESULT_BACKEND",
    "SECRET_KEY",
    "POSTGRES_PASSWORD",
]

# Internal service hostnames/ports this repo's docker-compose.yml
# actually defines (verified by reading it), used only to prove a
# --network none container cannot reach them.
INTERNAL_TARGETS = {
    "postgres_compose_service": ("aikdap_postgres", 5432),
    "redis_compose_service": ("aikdap_redis", 6379),
    "ollama_host_gateway": ("host.docker.internal", 11434),
    "cloud_metadata_endpoint": ("169.254.169.254", 80),
    "public_internet": ("1.1.1.1", 443),
    "localhost": ("127.0.0.1", 8000),
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], timeout: float | None = None, input_bytes: bytes | None = None):
    """Run a real subprocess, return (returncode, stdout, stderr, elapsed_seconds)."""
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=timeout, input=input_bytes
        )
        elapsed = time.perf_counter() - start
        return proc.returncode, proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace"), elapsed
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        return None, (exc.stdout or b"").decode(errors="replace"), (exc.stderr or b"").decode(errors="replace"), elapsed


def bench_name(prefix: str) -> str:
    return f"phase7a-{prefix}-{uuid.uuid4().hex[:8]}"


def docker_rm_f(name: str) -> None:
    run(["docker", "rm", "-f", name], timeout=15)


# ---------------------------------------------------------------------------
# Part A -- host/docker evidence
# ---------------------------------------------------------------------------


def part_a_host_evidence() -> dict:
    rc, out, err, _ = run(["docker", "version"], timeout=15)
    version_out = out
    rc2, out2, err2, _ = run(["docker", "info"], timeout=15)
    info_out = out2
    rc3, out3, _, _ = run(["uname", "-a"], timeout=10)
    return {
        "docker_version_stdout": version_out,
        "docker_info_stdout": info_out,
        "uname_a": out3.strip(),
    }


# ---------------------------------------------------------------------------
# Part C -- network isolation
# ---------------------------------------------------------------------------


def part_c_network_isolation() -> dict:
    results = {}
    for label, (host, port) in INTERNAL_TARGETS.items():
        name = bench_name("net")
        script = (
            "import socket,sys\n"
            f"s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.settimeout(3)\n"
            "try:\n"
            f"    s.connect(('{host}', {port}))\n"
            "    print('CONNECTED')\n"
            "except Exception as e:\n"
            "    print('FAILED:' + type(e).__name__ + ':' + str(e))\n"
        )
        cmd = [
            "docker", "run", "--rm", "--name", name,
            "--network", "none",
            "--memory", "64m", "--cpus", "0.5",
            ALPINE_IMAGE if False else PYTHON_IMAGE,
            "python3", "-c", script,
        ]
        rc, out, err, elapsed = run(cmd, timeout=20)
        results[label] = {
            "target": f"{host}:{port}",
            "command": " ".join(cmd),
            "exit_code": rc,
            "stdout": out.strip(),
            "stderr": err.strip()[-500:],
            "elapsed_seconds": round(elapsed, 3),
            "network_reachable": "CONNECTED" in out,
        }
    return results


# ---------------------------------------------------------------------------
# Part D -- filesystem isolation
# ---------------------------------------------------------------------------


def part_d_filesystem_isolation() -> dict:
    name = bench_name("fs")
    script = (
        "import os\n"
        "checks = {\n"
        "    'root_listing': os.listdir('/'),\n"
        "    'app_source_dir_exists': os.path.isdir('/app') and bool(os.listdir('/app')) if os.path.isdir('/app') else False,\n"
        "    'dotenv_exists': os.path.exists('/app/.env') or os.path.exists('/.env'),\n"
        "    'host_c_drive_exists': os.path.exists('/c') or os.path.exists('/mnt/c'),\n"
        "    'docker_socket_exists': os.path.exists('/var/run/docker.sock'),\n"
        "    'postgres_data_marker': os.path.exists('/var/lib/postgresql/data'),\n"
        "    'uploads_dir_exists': os.path.exists('/app/uploads'),\n"
        "}\n"
        "import json; print(json.dumps(checks))\n"
    )
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--memory", "64m", "--cpus", "0.5",
        PYTHON_IMAGE, "python3", "-c", script,
    ]
    rc, out, err, elapsed = run(cmd, timeout=20)

    # Separately inspect what mounts a container of this invocation
    # form actually has -- run one more (kept alive briefly) so
    # `docker inspect` can report its real .Mounts.
    name2 = bench_name("fs-mounts")
    cmd2 = [
        "docker", "run", "-d", "--name", name2,
        "--network", "none", "--memory", "64m", "--cpus", "0.5",
        PYTHON_IMAGE, "sleep", "5",
    ]
    rc2, out2, err2, elapsed2 = run(cmd2, timeout=20)
    rc3, out3, err3, _ = run(["docker", "inspect", "--format", "{{json .Mounts}}", name2], timeout=15)
    docker_rm_f(name2)

    return {
        "isolation_probe": {
            "command": " ".join(cmd),
            "exit_code": rc,
            "stdout": out.strip(),
            "stderr": err.strip()[-500:],
            "elapsed_seconds": round(elapsed, 3),
        },
        "mounts_probe": {
            "command": " ".join(cmd2) + " && docker inspect --format '{{json .Mounts}}' " + name2,
            "docker_inspect_mounts_raw": out3.strip(),
            "mounts_present": out3.strip() not in ("", "null", "[]"),
        },
    }


# ---------------------------------------------------------------------------
# Part E -- environment isolation
# ---------------------------------------------------------------------------


def part_e_env_isolation() -> dict:
    name = bench_name("env")
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--memory", "64m", "--cpus", "0.5",
        "-e", "BENCH_MARKER=phase7a",
        PYTHON_IMAGE, "python3", "-c",
        "import os,json; print(json.dumps(sorted(os.environ.keys())))",
    ]
    rc, out, err, elapsed = run(cmd, timeout=20)
    try:
        present_keys = set(json.loads(out.strip()))
    except Exception:
        present_keys = set()

    leaked = sorted(k for k in KNOWN_SECRET_ENV_NAMES if k in present_keys)
    return {
        "command": " ".join(cmd[:-1]) + " python3 -c \"<print sorted env key names>\"",
        "exit_code": rc,
        "container_env_key_names": sorted(present_keys),
        "checked_secret_names": KNOWN_SECRET_ENV_NAMES,
        "leaked_secret_names": leaked,
        "secrets_absent": len(leaked) == 0,
        "elapsed_seconds": round(elapsed, 3),
    }


# ---------------------------------------------------------------------------
# Part F -- startup latency (genuine cold pull vs warm)
# ---------------------------------------------------------------------------


def part_f_startup_latency() -> dict:
    # Confirm the image is NOT already present, so the first `docker
    # run` below is a genuine cold pull+start, not a fabricated number.
    rc, out, _, _ = run(["docker", "images", "-q", ALPINE_IMAGE], timeout=15)
    already_cached = bool(out.strip())

    cold_result = None
    if not already_cached:
        name = bench_name("cold")
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", ALPINE_IMAGE, "true"]
        rc, out, err, elapsed = run(cmd, timeout=120)
        cold_result = {
            "command": " ".join(cmd),
            "image_was_cached_before": False,
            "exit_code": rc,
            "elapsed_seconds": round(elapsed, 3),
        }
    else:
        cold_result = {
            "note": f"{ALPINE_IMAGE} was already cached on this host before the benchmark ran; "
            "a genuine cold-pull number could not be measured without deleting a possibly-shared "
            "image, which this benchmark will not do. See warm-start measurements instead.",
            "image_was_cached_before": True,
        }

    # Warm-start repetitions: image is now guaranteed cached.
    warm_times = []
    reps = 7
    for _ in range(reps):
        name = bench_name("warm")
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", ALPINE_IMAGE, "true"]
        rc, out, err, elapsed = run(cmd, timeout=30)
        if rc == 0:
            warm_times.append(elapsed)

    # Also measure warm-start of python:3.12-slim (the image every
    # other benchmark part below actually uses), since that number is
    # the operationally relevant one for this benchmark's own later
    # parts, even though it is a separate image from the alpine
    # cold/warm pair above.
    rc, out, _, _ = run(["docker", "images", "-q", PYTHON_IMAGE], timeout=15)
    python_already_cached = bool(out.strip())
    python_pull_result = None
    if not python_already_cached:
        name = bench_name("pypull")
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", PYTHON_IMAGE, "true"]
        rc, out, err, elapsed = run(cmd, timeout=180)
        python_pull_result = {
            "command": " ".join(cmd),
            "image_was_cached_before": False,
            "exit_code": rc,
            "elapsed_seconds": round(elapsed, 3),
        }
    else:
        python_pull_result = {"image_was_cached_before": True}

    python_warm_times = []
    for _ in range(5):
        name = bench_name("pywarm")
        cmd = ["docker", "run", "--rm", "--name", name, "--network", "none", PYTHON_IMAGE, "true"]
        rc, out, err, elapsed = run(cmd, timeout=30)
        if rc == 0:
            python_warm_times.append(elapsed)

    def stats(values):
        if not values:
            return None
        return {
            "repetitions": len(values),
            "min_seconds": round(min(values), 3),
            "median_seconds": round(statistics.median(values), 3),
            "max_seconds": round(max(values), 3),
            "raw_seconds": [round(v, 3) for v in values],
        }

    return {
        "alpine_cold_start": cold_result,
        "alpine_warm_start": stats(warm_times),
        "python_slim_pull_or_cache_status": python_pull_result,
        "python_slim_warm_start": stats(python_warm_times),
    }


# ---------------------------------------------------------------------------
# Part G -- CPU limit behavior
# ---------------------------------------------------------------------------


def part_g_cpu_limit() -> dict:
    name = bench_name("cpu")
    cpu_limit = "0.5"
    duration = 4
    script = (
        "import time\n"
        f"deadline = time.time() + {duration}\n"
        "iterations = 0\n"
        "while time.time() < deadline:\n"
        "    iterations += 1\n"
        "print('iterations=' + str(iterations))\n"
    )
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--cpus", cpu_limit, "--memory", "64m",
        PYTHON_IMAGE, "python3", "-c", script,
    ]
    rc, out, err, elapsed = run(cmd, timeout=duration + 15)

    # Comparison run at a higher CPU limit, same wall-clock budget --
    # if the throttle is real, iteration count should scale with the
    # configured limit, not stay constant regardless of the flag.
    name2 = bench_name("cpu-cmp")
    cmd2 = [
        "docker", "run", "--rm", "--name", name2,
        "--network", "none", "--cpus", "2.0", "--memory", "64m",
        PYTHON_IMAGE, "python3", "-c", script,
    ]
    rc2, out2, err2, elapsed2 = run(cmd2, timeout=duration + 15)

    return {
        "configured_cpu_limit": cpu_limit,
        "workload_duration_seconds": duration,
        "run_at_0.5_cpu": {
            "command": " ".join(cmd),
            "exit_code": rc,
            "stdout": out.strip(),
            "elapsed_seconds": round(elapsed, 3),
        },
        "comparison_run_at_2.0_cpu": {
            "command": " ".join(cmd2),
            "exit_code": rc2,
            "stdout": out2.strip(),
            "elapsed_seconds": round(elapsed2, 3),
        },
        "interpretation_basis": "compare iteration counts between the two runs; a real CPU "
        "throttle should show materially fewer iterations at 0.5 CPU than at 2.0 CPU for the "
        "same wall-clock budget",
    }


# ---------------------------------------------------------------------------
# Part H -- memory limit behavior
# ---------------------------------------------------------------------------


def part_h_memory_limit() -> dict:
    name = bench_name("mem")
    mem_limit = "100m"
    # Intentionally allocate well past the limit, in small growing
    # chunks, touching every page (bytearray() alone does not commit
    # pages; writing to it does) so the kernel/cgroup actually has to
    # account for real resident memory.
    script = (
        "import time\n"
        "chunks = []\n"
        "try:\n"
        "    for i in range(1, 40):\n"
        "        b = bytearray(20 * 1024 * 1024)\n"
        "        for j in range(0, len(b), 4096):\n"
        "            b[j] = 1\n"
        "        chunks.append(b)\n"
        "        print('allocated_mb=' + str(i * 20), flush=True)\n"
        "        time.sleep(0.05)\n"
        "    print('COMPLETED_WITHOUT_OOM')\n"
        "except MemoryError:\n"
        "    print('PYTHON_MEMORY_ERROR')\n"
    )
    cmd = [
        "docker", "run", "--name", name,
        "--network", "none", "--memory", mem_limit, "--memory-swap", mem_limit,
        PYTHON_IMAGE, "python3", "-c", script,
    ]
    rc, out, err, elapsed = run(cmd, timeout=60)

    rc_inspect, inspect_out, _, _ = run(
        ["docker", "inspect", "--format", "{{.State.OOMKilled}} {{.State.ExitCode}} {{.State.Status}}", name],
        timeout=15,
    )
    docker_rm_f(name)

    host_alive_rc, host_alive_out, _, _ = run(["docker", "info"], timeout=15)

    return {
        "configured_memory_limit": mem_limit,
        "command": " ".join(cmd),
        "process_exit_code": rc,
        "stdout_tail": "\n".join(out.strip().splitlines()[-6:]),
        "stderr_tail": err.strip()[-500:],
        "elapsed_seconds": round(elapsed, 3),
        "docker_inspect_oomkilled_exitcode_status": inspect_out.strip(),
        "host_docker_daemon_responsive_after": host_alive_rc == 0,
    }


# ---------------------------------------------------------------------------
# Part I -- external wall-clock timeout enforcement
# ---------------------------------------------------------------------------


def part_i_external_timeout() -> dict:
    name = bench_name("timeout")
    sleep_seconds = 120
    external_timeout_seconds = 5

    cmd_start = [
        "docker", "run", "-d", "--name", name,
        "--network", "none", "--memory", "64m", "--cpus", "0.5",
        PYTHON_IMAGE, "python3", "-c", f"import time; time.sleep({sleep_seconds})",
    ]
    rc_start, out_start, err_start, elapsed_start = run(cmd_start, timeout=20)

    # Host-side wait, NOT signal.alarm, NOT any code inside the
    # container -- a plain external sleep, then an unconditional kill.
    time.sleep(external_timeout_seconds)

    kill_start = time.perf_counter()
    rc_kill, out_kill, err_kill, _ = run(["docker", "kill", name], timeout=15)
    rc_wait, out_wait, err_wait, _ = run(["docker", "wait", name], timeout=15)
    kill_elapsed = time.perf_counter() - kill_start

    rc_inspect, inspect_out, _, _ = run(
        ["docker", "inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", name], timeout=15
    )
    rc_ps, ps_out, _, _ = run(["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"], timeout=15)
    still_running = name in ps_out
    docker_rm_f(name)

    return {
        "workload_sleep_seconds": sleep_seconds,
        "external_timeout_budget_seconds": external_timeout_seconds,
        "start_command": " ".join(cmd_start),
        "start_exit_code": rc_start,
        "container_status_after_kill": inspect_out.strip(),
        "container_exit_code_wait": out_wait.strip(),
        "kill_to_confirmed_stopped_seconds": round(kill_elapsed, 3),
        "container_still_running_after_kill": still_running,
        "enforcement_mechanism": "host-side time.sleep() + docker kill, no signal.alarm, no in-container cooperation",
    }


# ---------------------------------------------------------------------------
# Part J -- cancellation, including child processes
# ---------------------------------------------------------------------------


def part_j_cancellation() -> dict:
    name = bench_name("cancel")
    # A SAFE, bounded number of child sleep processes -- not a fork
    # bomb. 8 children, each just sleeping.
    script = (
        "import subprocess, time\n"
        "children = [subprocess.Popen(['sleep', '300']) for _ in range(8)]\n"
        "print('children_started=' + str(len(children)), flush=True)\n"
        "time.sleep(300)\n"
    )
    cmd_start = [
        "docker", "run", "-d", "--name", name,
        "--network", "none", "--memory", "64m", "--cpus", "0.5", "--pids-limit", "32",
        PYTHON_IMAGE, "python3", "-c", script,
    ]
    rc_start, out_start, err_start, _ = run(cmd_start, timeout=20)

    time.sleep(2)  # let children actually spawn

    rc_top, top_out, top_err, _ = run(["docker", "top", name], timeout=15)
    process_lines_before = [l for l in top_out.strip().splitlines() if l.strip()]

    cancel_start = time.perf_counter()
    rc_stop, out_stop, err_stop, _ = run(["docker", "stop", "-t", "5", name], timeout=20)
    cancel_elapsed = time.perf_counter() - cancel_start

    rc_inspect, inspect_out, _, _ = run(
        ["docker", "inspect", "--format", "{{.State.Status}}", name], timeout=15
    )
    rc_ps, ps_out, _, _ = run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}\t{{.Status}}"], timeout=15)
    docker_rm_f(name)

    return {
        "start_command": " ".join(cmd_start),
        "children_spawned_intended": 8,
        "docker_top_before_cancel_process_line_count": len(process_lines_before) - 1 if process_lines_before else 0,
        "docker_top_before_cancel_raw": top_out.strip(),
        "cancel_command": f"docker stop -t 5 {name}",
        "cancel_to_confirmed_stopped_seconds": round(cancel_elapsed, 3),
        "container_status_after_stop": inspect_out.strip(),
        "docker_ps_after_stop": ps_out.strip(),
    }


# ---------------------------------------------------------------------------
# Part K -- output limiting primitives
# ---------------------------------------------------------------------------


def part_k_output_limit() -> dict:
    name = bench_name("output")
    # Emits far more than the byte ceiling below produces, so the
    # test proves truncation actually happens rather than the
    # workload just happening to be small.
    total_lines = 2_000_000
    script = (
        f"for i in range({total_lines}):\n"
        "    print('x' * 100)\n"
    )
    byte_ceiling = 1_000_000  # 1 MB

    start = time.perf_counter()
    proc = subprocess.Popen(
        [
            "docker", "run", "--rm", "--name", name,
            "--network", "none", "--memory", "64m", "--cpus", "0.5",
            PYTHON_IMAGE, "python3", "-c", script,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    collected = b""
    truncated = False
    try:
        while len(collected) < byte_ceiling:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            collected += chunk
        if len(collected) >= byte_ceiling:
            truncated = True
            proc.stdout.close()  # host stops reading -> SIGPIPE/broken pipe on the writer side
    finally:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
    elapsed = time.perf_counter() - start
    docker_rm_f(name)

    return {
        "byte_ceiling": byte_ceiling,
        "total_lines_workload_would_emit_if_unbounded": total_lines,
        "bytes_actually_collected": len(collected),
        "host_stopped_reading_early": truncated,
        "container_process_exit_code": proc.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "primitive_demonstrated": "host-side bounded read loop over docker run's stdout pipe; "
        "closing the pipe after the ceiling is reached causes the container's write to fail "
        "(broken pipe) rather than buffering the full unbounded output host-side",
        "production_collector_note": "no production collector exists or was created; this only "
        "benchmarks the read-and-stop-early primitive a future collector would need to build on",
    }


# ---------------------------------------------------------------------------
# Part L -- cleanup timing
# ---------------------------------------------------------------------------


def part_l_cleanup() -> dict:
    name = bench_name("cleanup")
    cmd_start = [
        "docker", "run", "-d", "--name", name,
        "--network", "none", "--memory", "64m", "--cpus", "0.5",
        PYTHON_IMAGE, "python3", "-c",
        "open('/tmp/phase7a_scratch.bin','wb').write(b'0'*1048576); import time; time.sleep(60)",
    ]
    rc_start, out_start, err_start, _ = run(cmd_start, timeout=20)
    time.sleep(1.5)

    term_start = time.perf_counter()
    run(["docker", "stop", "-t", "3", name], timeout=15)
    term_elapsed = time.perf_counter() - term_start

    rc_ps1, ps1_out, _, _ = run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"], timeout=15)
    terminated_but_present = name in ps1_out

    rm_start = time.perf_counter()
    run(["docker", "rm", name], timeout=15)
    rm_elapsed = time.perf_counter() - rm_start

    rc_ps2, ps2_out, _, _ = run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"], timeout=15)
    fully_removed = name not in ps2_out

    # Broad orphan check: any container whose name starts with our
    # phase7a- prefix left behind by this run.
    rc_orphan, orphan_out, _, _ = run(
        ["docker", "ps", "-a", "--filter", "name=phase7a-", "--format", "{{.Names}}\t{{.Status}}"], timeout=15
    )

    return {
        "terminate_command": f"docker stop -t 3 {name}",
        "terminate_to_stopped_seconds": round(term_elapsed, 3),
        "container_present_after_stop": terminated_but_present,
        "remove_command": f"docker rm {name}",
        "stopped_to_removed_seconds": round(rm_elapsed, 3),
        "container_fully_removed": fully_removed,
        "orphan_check_docker_ps_a_phase7a_prefix": orphan_out.strip(),
        "note": "the scratch file written inside the container's own writable layer is destroyed "
        "with the container on `docker rm`, since no volume was mounted for it -- verified by the "
        "absence of any bind mount in Part D's mounts probe",
    }


# ---------------------------------------------------------------------------
# Part M -- small, safe concurrency baseline
# ---------------------------------------------------------------------------


def part_m_concurrency() -> dict:
    n = 3
    duration = 3
    names = [bench_name(f"conc{i}") for i in range(n)]
    script = f"import time; time.sleep({duration}); print('done')"

    overall_start = time.perf_counter()
    procs = []
    launch_times = []
    for name in names:
        t0 = time.perf_counter()
        p = subprocess.Popen(
            [
                "docker", "run", "--rm", "--name", name,
                "--network", "none", "--memory", "64m", "--cpus", "0.5",
                PYTHON_IMAGE, "python3", "-c", script,
            ],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        procs.append(p)
        launch_times.append(time.perf_counter() - t0)

    results = []
    host_check_rc, host_check_out, _, host_check_elapsed = None, None, None, None
    for p, name in zip(procs, names):
        out, err = p.communicate(timeout=60)
        results.append({"name": name, "exit_code": p.returncode, "stdout": out.decode(errors="replace").strip()})

    overall_elapsed = time.perf_counter() - overall_start

    # Host responsiveness check performed WHILE the above were running
    # would be more informative, but subprocess.Popen().communicate()
    # blocks; instead measure a `docker ps` call immediately after,
    # which still demonstrates the daemon/CLI remained functional
    # throughout (a hung daemon would make this call itself slow/hang).
    hrc, hout, _, helapsed = run(["docker", "ps"], timeout=15)

    return {
        "concurrent_container_count": n,
        "per_container_workload_seconds": duration,
        "launch_call_seconds_each": [round(t, 3) for t in launch_times],
        "results": results,
        "all_succeeded": all(r["exit_code"] == 0 for r in results),
        "total_wall_seconds_for_all_n": round(overall_elapsed, 3),
        "sequential_would_have_taken_at_least_seconds": duration * n,
        "host_docker_ps_after_seconds": round(helapsed, 3),
        "host_responsive_after": hrc == 0,
        "caveat": "n=3 is a safety-bounded sample, not a production concurrency-cap measurement; "
        "see Phase 7 design review Section 10/28 for what a real cap derivation would require",
    }


def main() -> None:
    RESULTS["generated_at"] = now_iso()

    print("Part A: host/docker evidence", file=sys.stderr)
    part_a = part_a_host_evidence()
    RESULTS["docker_version"] = part_a["docker_version_stdout"].splitlines()[1] if part_a["docker_version_stdout"] else None
    RESULTS["host_context"] = part_a["uname_a"]
    RESULTS["parts"]["A_host_evidence"] = part_a

    print("Part C: network isolation", file=sys.stderr)
    RESULTS["parts"]["C_network_isolation"] = part_c_network_isolation()

    print("Part D: filesystem isolation", file=sys.stderr)
    RESULTS["parts"]["D_filesystem_isolation"] = part_d_filesystem_isolation()

    print("Part E: environment/secret isolation", file=sys.stderr)
    RESULTS["parts"]["E_env_isolation"] = part_e_env_isolation()

    print("Part F: startup latency", file=sys.stderr)
    RESULTS["parts"]["F_startup_latency"] = part_f_startup_latency()

    print("Part G: CPU limit behavior", file=sys.stderr)
    RESULTS["parts"]["G_cpu_limit"] = part_g_cpu_limit()

    print("Part H: memory limit behavior", file=sys.stderr)
    RESULTS["parts"]["H_memory_limit"] = part_h_memory_limit()

    print("Part I: external wall-clock timeout", file=sys.stderr)
    RESULTS["parts"]["I_external_timeout"] = part_i_external_timeout()

    print("Part J: cancellation", file=sys.stderr)
    RESULTS["parts"]["J_cancellation"] = part_j_cancellation()

    print("Part K: output limiting primitive", file=sys.stderr)
    RESULTS["parts"]["K_output_limit"] = part_k_output_limit()

    print("Part L: cleanup timing", file=sys.stderr)
    RESULTS["parts"]["L_cleanup"] = part_l_cleanup()

    print("Part M: small concurrency baseline", file=sys.stderr)
    RESULTS["parts"]["M_concurrency"] = part_m_concurrency()

    out_path = "results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    print(f"\nResults written to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
