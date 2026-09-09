"""
Benchmark Driver for Native C SSD Controller Firmware Prototype.
Runs FIFO, AI-Priority, and TEMPO against real host CHEOPS traces.
"""

import os
import subprocess
import json

CONTROLLER_EXE = os.path.join("tempo_controller", "tempo_controller.exe")
TRACE_PATH = os.path.join(
    "temp_cheops",
    "results",
    "figure5-6-kv-offloading-flexgen",
    "flexgen-kv-offload-opt-6.7b-bs-64-ext4-trace",
    "opt-6.7b-kv-offload-bs-64-ext4-bpftrace-block.txt"
)

POLICIES = ["fifo", "ai_priority", "tempo"]

def run_controller_benchmark(requests=1500, slack=800.0, bg_iops=200.0, qd=32, seed=42):
    results = {}
    for pol in POLICIES:
        cmd = [
            CONTROLLER_EXE,
            "--trace", TRACE_PATH,
            "--policy", pol,
            "--requests", str(requests),
            "--slack", str(slack),
            "--bg-iops", str(bg_iops),
            "--qd", str(qd),
            "--seed", str(seed),
            "--json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        results[pol] = json.loads(res.stdout)
    return results

def main():
    print("=" * 72)
    print("  PROJECT TEMPO: NATIVE C CONTROLLER PROTOTYPE BENCHMARK")
    print("  Evaluating Host NVMe I/O on CHEOPS OPT-6.7B KV-Cache Block Trace")
    print("=" * 72)

    results = run_controller_benchmark()
    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "prototype_controller_results.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved raw prototype benchmark telemetry to: {out_file}\n")
    print(f"{'Policy':<16} | {'Miss %':<8} | {'P50 (µs)':<9} | {'P95 (µs)':<9} | {'P99 (µs)':<9} | {'Throughput':<11} | {'ARM Cycle Est':<13}")
    print("-" * 88)
    for pol in POLICIES:
        d = results[pol]
        print(f"{d['policy']:<16} | {d['miss_pct']:>6.2f}% | {d['p50_us']:>9.1f} | {d['p95_us']:>9.1f} | {d['p99_us']:>9.1f} | {d['throughput_mb_s']:>7.1f} MB/s | {d['projected_arm_us']:>7.3f} µs")
    print("=" * 88)

    s1_miss = results["ai_priority"]["miss_pct"]
    s3_miss = results["tempo"]["miss_pct"]
    diff_pp = s1_miss - s3_miss
    p95_win = results["ai_priority"]["p95_us"] - results["tempo"]["p95_us"]

    print(f"\n[PROTOTYPE VERDICT]")
    print(f"  * Critical Miss Reduction: {diff_pp:.2f} percentage points ({s1_miss:.2f}% -> {s3_miss:.2f}%)")
    print(f"  * P95 Tail Latency Win:    {p95_win:.1f} µs ({results['ai_priority']['p95_us']:.1f} µs -> {results['tempo']['p95_us']:.1f} µs)")
    print(f"  * Hardware Viability:      TEMPO decision executes in firmware inside the NVMe submission loop.\n")

if __name__ == "__main__":
    main()
