"""Sprint 16 Phase 7A.5 -- representative workload profiling.

BENCHMARK-ONLY INFRASTRUCTURE. Not part of the application. Implements
no execution engine, endpoint, or worker. Runs only synthetic,
in-memory-generated data through the real, already-built
`aikdap-backend:latest` image (chosen because it already has the
production-pinned numpy/pandas/sympy versions -- verified live before
this script was written -- so no new image had to be built and no
production dependency was added anywhere). Every container run uses
`--network none`, no volume mounts, and a minimal explicit `-e` list
only -- identical safety posture to Phase 7A.

Writes results to `results.json` next to this file.
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import textwrap
import time
import uuid
from datetime import datetime, timezone

IMAGE = "phase7a5-benchmark:local"
RESULTS: dict = {
    "benchmark_suite": "sprint16-phase7a5-workload-profiling",
    "generated_at": None,
    "docker_version": None,
    "image_used": IMAGE,
    "parts": {},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def name() -> str:
    return f"phase7a5-{uuid.uuid4().hex[:8]}"


def run(cmd: list[str], timeout: float | None = None):
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        elapsed = time.perf_counter() - start
        return proc.returncode, proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace"), elapsed
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - start
        return None, (exc.stdout or b"").decode(errors="replace"), (exc.stderr or b"").decode(errors="replace"), elapsed


def docker_rm_f(n: str) -> None:
    run(["docker", "rm", "-f", n], timeout=15)


def parse_result_line(stdout: str) -> dict | None:
    for line in stdout.splitlines():
        if line.startswith("RESULT:"):
            try:
                return json.loads(line[len("RESULT:"):])
            except json.JSONDecodeError:
                return None
    return None


def run_workload(
    script: str,
    *,
    cpus: str = "2.0",
    mem: str = "2g",
    timeout: float = 120,
    pids_limit: str = "32",
) -> dict:
    """Run one synthetic workload script inside a fresh, disposable,
    network-isolated container built from the image every part of this
    benchmark reuses. Returns host-side total wall time plus whatever
    the workload itself self-reported via a RESULT: JSON line.

    OPENBLAS_NUM_THREADS is pinned to the configured CPU quota
    (minimum 1) -- discovered live while building this benchmark that
    OpenBLAS otherwise spawns one thread per HOST-visible core (20 on
    this VM, since `--cpus` throttles CPU time without reducing
    `os.cpu_count()`), which both defeats the point of a per-job CPU
    quota (oversubscription) and, combined with a tight `--pids-limit`,
    crashes numpy outright (`pthread_create` EAGAIN -> SIGSEGV inside
    OpenBLAS's own error path, which numpy's generic import-error
    handler then misreports as "wrong source directory"). This is
    itself a real finding, reported in Section 6/13, not merely a
    harness workaround.
    """
    n = name()
    try:
        openblas_threads = max(1, int(float(cpus)))
    except ValueError:
        openblas_threads = 2
    cmd = [
        "docker", "run", "--rm", "--name", n,
        "--network", "none", "--cpus", cpus, "--memory", mem, "--pids-limit", pids_limit,
        "-e", f"OPENBLAS_NUM_THREADS={openblas_threads}",
        "-e", f"OMP_NUM_THREADS={openblas_threads}",
        "--entrypoint", "python3", IMAGE, "-c", script,
    ]
    rc, out, err, elapsed = run(cmd, timeout=timeout)
    parsed = parse_result_line(out)
    return {
        "exit_code": rc,
        "host_total_wall_seconds": round(elapsed, 4),
        "workload_self_reported": parsed,
        "stdout_tail": "\n".join(out.strip().splitlines()[-3:]),
        "stderr_tail": err.strip()[-400:],
    }


def repeated(script: str, reps: int, **kwargs) -> dict:
    runs = [run_workload(script, **kwargs) for _ in range(reps)]
    host_times = [r["host_total_wall_seconds"] for r in runs if r["exit_code"] == 0]
    workload_times = [
        r["workload_self_reported"]["workload_seconds"]
        for r in runs
        if r["exit_code"] == 0 and r["workload_self_reported"]
    ]
    maxrss = [
        r["workload_self_reported"]["maxrss_kb"]
        for r in runs
        if r["exit_code"] == 0 and r["workload_self_reported"]
    ]

    def stats(vals):
        if not vals:
            return None
        return {
            "repetitions": len(vals),
            "min": round(min(vals), 4) if isinstance(vals[0], float) else min(vals),
            "median": round(statistics.median(vals), 4) if isinstance(vals[0], float) else statistics.median(vals),
            "max": round(max(vals), 4) if isinstance(vals[0], float) else max(vals),
            "raw": vals,
        }

    return {
        "repetitions_attempted": reps,
        "successful_runs": len(host_times),
        "host_total_wall_seconds": stats(host_times),
        "workload_internal_seconds": stats(workload_times),
        "maxrss_kb": stats(maxrss),
        "container_overhead_seconds_estimate": (
            round(statistics.median(host_times) - statistics.median(workload_times), 4)
            if host_times and workload_times
            else None
        ),
        "raw_runs": runs,
    }


# ---------------------------------------------------------------------------
# Workload scripts (synthetic, in-memory only, no network, no disk beyond
# an in-process string/buffer)
# ---------------------------------------------------------------------------


def w_numpy_matmul(n: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, json
        import numpy as np
        n = {n}
        t0 = time.perf_counter()
        rng = np.random.default_rng(1)
        a = rng.random((n, n))
        b = rng.random((n, n))
        c = a @ b
        checksum = float(np.trace(c))
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'n': n, 'checksum': checksum}}))
    """).strip()


def w_pandas_groupby(rows: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, json
        import numpy as np, pandas as pd
        rows = {rows}
        t0 = time.perf_counter()
        rng = np.random.default_rng(2)
        df = pd.DataFrame({{
            'group': rng.integers(0, 50, rows),
            'a': rng.random(rows),
            'b': rng.random(rows),
            'c': rng.random(rows),
            'd': rng.integers(0, 1000, rows),
        }})
        agg = df.groupby('group').agg({{'a': 'mean', 'b': 'std', 'c': 'sum', 'd': 'max'}})
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'rows': rows, 'output_rows': len(agg)}}))
    """).strip()


def w_sympy_symbolic(label: str, expr_str: str) -> str:
    return textwrap.dedent(f"""
        import time, resource, json
        import sympy
        expr_str = {expr_str!r}
        t0 = time.perf_counter()
        expr = sympy.sympify(expr_str)
        simplified = sympy.simplify(expr)
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'label': {label!r}, 'expr_len': len(expr_str)}}))
    """).strip()


def w_mixed_pipeline(rows: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, json
        import numpy as np, pandas as pd
        rows = {rows}
        t0 = time.perf_counter()
        rng = np.random.default_rng(3)
        arr = np.cumsum(rng.standard_normal(rows))
        df = pd.DataFrame({{'value': arr}})
        df['rolling_mean'] = df['value'].rolling(50, min_periods=1).mean()
        df['rolling_std'] = df['value'].rolling(50, min_periods=1).std()
        fft_input = arr[:min(rows, 4096)]
        fft_result = np.fft.fft(fft_input)
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'rows': rows, 'fft_len': len(fft_input)}}))
    """).strip()


def w_transform_pipeline(rows: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, io, json
        import numpy as np, pandas as pd
        rows = {rows}
        t0 = time.perf_counter()
        rng = np.random.default_rng(4)
        categories = ['A', 'B', 'C', 'D']
        regions = ['north', 'south', 'east', 'west']
        lines = ['id,category,region,value']
        vals = rng.random(rows) * 100
        for i in range(rows):
            lines.append(f"{{i}},{{categories[i % 4]}},{{regions[i % 4]}},{{vals[i]:.4f}}")
        csv_text = '\\n'.join(lines)
        df = pd.read_csv(io.StringIO(csv_text))
        pivot = df.pivot_table(index='category', columns='region', values='value', aggfunc='mean')
        output_csv = pivot.to_csv()
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'rows': rows, 'input_csv_bytes': len(csv_text), 'output_csv_bytes': len(output_csv)}}))
    """).strip()


def w_viz_prep(n: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, random, json
        n = {n}
        random.seed(5)
        t0 = time.perf_counter()
        pairs = [(i, random.random() * 100) for i in range(n)]
        pairs.sort(key=lambda p: p[1])
        series = {{'x': [p[0] for p in pairs], 'y': [p[1] for p in pairs]}}
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'n': n, 'series_len': len(series['x'])}}))
    """).strip()


def w_statistics(n: int) -> str:
    return textwrap.dedent(f"""
        import time, resource, json
        import numpy as np
        n = {n}
        t0 = time.perf_counter()
        rng = np.random.default_rng(6)
        data = rng.standard_normal(n)
        other = rng.standard_normal(n)
        mean = float(np.mean(data))
        std = float(np.std(data))
        p50 = float(np.percentile(data, 50))
        p95 = float(np.percentile(data, 95))
        corr = float(np.corrcoef(data, other)[0, 1])
        elapsed = time.perf_counter() - t0
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print('RESULT:' + json.dumps({{'workload_seconds': elapsed, 'maxrss_kb': maxrss, 'n': n, 'mean': mean, 'std': std}}))
    """).strip()


# ---------------------------------------------------------------------------
# Part orchestration
# ---------------------------------------------------------------------------

REPS = 3  # deliberately small; every stat below is labeled n=3, no invented percentiles

DATASET_SIZES = {"small": 10_000, "medium": 100_000, "larger": 500_000}
MATMUL_SIZES = {"small": 400, "medium": 800, "larger": 1200}
VIZ_SIZES = {"small": 1_000, "medium": 10_000, "larger": 100_000}
STAT_SIZES = {"small": 10_000, "medium": 100_000, "larger": 1_000_000}
SYMPY_EXPRS = {
    "small": "(a*x + b) / (c*x + d)",
    "medium": "sin(a*x) + cos(b*x) + sqrt(x**2 + 1) / (c*x + d)",
    "large": "sin(a*x) + cos(b*x) + tan(c*x)/2 + sqrt(x**2+1)/(d*x+1) + exp(-x**2) + "
    "(a*x**3 + b*x**2 + c*x + d) / (x**4 + 1) + log(x**2 + 1) + sin(x)*cos(x)*exp(-x/10)",
}


def part_c_to_g_workloads() -> dict:
    results = {}

    print("  workload 1/7: numpy matmul", file=sys.stderr)
    results["1_numpy_matmul"] = {
        size: repeated(w_numpy_matmul(n), REPS) for size, n in MATMUL_SIZES.items()
    }

    print("  workload 2/7: pandas groupby", file=sys.stderr)
    results["2_pandas_groupby"] = {
        size: repeated(w_pandas_groupby(n), REPS) for size, n in DATASET_SIZES.items()
    }

    print("  workload 3/7: sympy symbolic", file=sys.stderr)
    results["3_sympy_symbolic"] = {
        label: repeated(w_sympy_symbolic(label, expr), REPS)
        for label, expr in SYMPY_EXPRS.items()
    }

    print("  workload 4/7: mixed numpy+pandas pipeline", file=sys.stderr)
    results["4_mixed_pipeline"] = {
        size: repeated(w_mixed_pipeline(n), REPS) for size, n in DATASET_SIZES.items()
    }

    print("  workload 5/7: transform pipeline (csv in/out)", file=sys.stderr)
    results["5_transform_pipeline"] = {
        size: repeated(w_transform_pipeline(n), REPS) for size, n in DATASET_SIZES.items()
    }

    print("  workload 6/7: visualization-data prep", file=sys.stderr)
    results["6_viz_prep"] = {
        size: repeated(w_viz_prep(n), REPS) for size, n in VIZ_SIZES.items()
    }

    print("  workload 7/7: simple statistics", file=sys.stderr)
    results["7_statistics"] = {
        size: repeated(w_statistics(n), REPS) for size, n in STAT_SIZES.items()
    }

    return results


def part_e_cpu_comparison() -> dict:
    script = w_numpy_matmul(MATMUL_SIZES["larger"])
    out = {}
    for cpus in ("0.5", "1.0", "2.0"):
        out[f"cpus_{cpus}"] = repeated(script, REPS, cpus=cpus, mem="2g")
    return out


def part_i_concurrency() -> dict:
    script = w_mixed_pipeline(DATASET_SIZES["medium"])
    levels = [1, 2, 4, 8]
    out = {}
    for level in levels:
        overall_start = time.perf_counter()
        procs = []
        for _ in range(level):
            n = name()
            p = subprocess.Popen(
                [
                    "docker", "run", "--rm", "--name", n,
                    "--network", "none", "--cpus", "1.0", "--memory", "256m", "--pids-limit", "32",
                    "-e", "OPENBLAS_NUM_THREADS=1", "-e", "OMP_NUM_THREADS=1",
                    "--entrypoint", "python3", IMAGE, "-c", script,
                ],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            procs.append(p)
        job_results = []
        for p in procs:
            out_b, err_b = p.communicate(timeout=180)
            job_results.append({
                "exit_code": p.returncode,
                "parsed": parse_result_line(out_b.decode(errors="replace")),
            })
        overall_elapsed = time.perf_counter() - overall_start

        rc_ps, ps_out, _, ps_elapsed = run(["docker", "ps"], timeout=15)
        job_internal_times = [
            r["parsed"]["workload_seconds"] for r in job_results if r["exit_code"] == 0 and r["parsed"]
        ]
        out[f"level_{level}"] = {
            "concurrent_containers": level,
            "successful": sum(1 for r in job_results if r["exit_code"] == 0),
            "total_wall_seconds": round(overall_elapsed, 3),
            "median_job_internal_seconds": round(statistics.median(job_internal_times), 4) if job_internal_times else None,
            "docker_ps_responsive_seconds": round(ps_elapsed, 3),
            "docker_ps_ok": rc_ps == 0,
        }
    return out


def main() -> None:
    RESULTS["generated_at"] = now_iso()
    rc, out, _, _ = run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=15)
    RESULTS["docker_version"] = out.strip()

    print("Parts C-G: 7 workload categories x sizes x reps", file=sys.stderr)
    RESULTS["parts"]["C_to_G_workloads"] = part_c_to_g_workloads()

    print("Part E (dedicated): CPU 0.5/1.0/2.0 comparison on numpy matmul", file=sys.stderr)
    RESULTS["parts"]["E_cpu_comparison"] = part_e_cpu_comparison()

    print("Part I: concurrency 1/2/4/8", file=sys.stderr)
    RESULTS["parts"]["I_concurrency"] = part_i_concurrency()

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, indent=2)
    print("\nResults written to results.json", file=sys.stderr)


if __name__ == "__main__":
    main()
