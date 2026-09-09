"""Phase 6: Multi-Window Statistical Analysis (Mean, Median, Std, CI95, P99.9)."""

import copy
import json
import os
import time
import numpy as np
from typing import List, Dict, Any
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator, SimulationResult
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

# Student's t multiplier for 95% two-tailed confidence interval with df = 4 (N = 5 runs)
T_CRIT_95_DF4 = 2.776

def run_multirun_statistical_analysis(
    window_offsets: List[int] = [70000, 140000, 210000, 280000, 350000],
    num_requests_per_window: int = 2000,
    critical_fraction: float = 0.4,
    deadline_slack_us: float = 800.0,
    bg_iops: float = 200.0,
    qd: int = 32
) -> Dict[str, Any]:
    """
    Executes multiple independent experimental runs across distinct non-overlapping
    trace windows from the 25.2M-request CHEOPS trace.
    Computes Mean, Median, Std, and 95% Confidence Intervals for:
    - Miss Count & Miss Percentage
    - Critical P50, P95, P99, P99.9, Max latency
    """
    print("=" * 115)
    print("PHASE 6: MULTI-WINDOW STATISTICAL ANALYSIS & REPEATED RUNS")
    print(f"Trace Windows: {len(window_offsets)} independent segments across CHEOPS KV-cache trace")
    print(f"Offsets: {window_offsets} (Lines) | Requests/Window: {num_requests_per_window}")
    print(f"Fixed: Deadline Slack = {deadline_slack_us} us, Background Write = {bg_iops} IOPS, QD = {qd}")
    print("=" * 115)

    schedulers_factory = [
        ("S0-FIFO", lambda: FIFOScheduler()),
        ("S1-AI-Priority", lambda: AIPriorityScheduler()),
        ("S2-SSD-State", lambda: SSDStateScheduler()),
        ("S3-AI+SSD-State", lambda: AIAndSSDStateScheduler())
    ]

    # Structure to hold runs per scheduler
    run_records: Dict[str, List[SimulationResult]] = {name: [] for name, _ in schedulers_factory}

    for w_idx, offset in enumerate(window_offsets, 1):
        print(f"\n[Window {w_idx}/{len(window_offsets)}] Loading {num_requests_per_window} requests starting at line {offset}...")
        t0 = time.time()
        base_reqs = WorkloadGenerator.get_kv_offload_slice(
            num_requests=num_requests_per_window,
            skip_initial=offset,
            critical_fraction=critical_fraction,
            deadline_slack_us=deadline_slack_us
        )
        if bg_iops > 0:
            base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=bg_iops)
        print(f"Loaded in {time.time() - t0:.2f}s. Running all 4 schedulers...")

        for name, factory in schedulers_factory:
            sched = factory()
            sim = Simulator(config=SSDConfig(), max_in_flight=qd)
            res = sim.run(copy.deepcopy(base_reqs), sched)
            run_records[name].append(res)
            print(f"  {name:<18} -> Crit P95: {res.critical_p95_us:6.1f} us | P99.9: {res.critical_p99_9_us:6.1f} us | Misses: {res.critical_deadline_misses:3d} ({res.critical_deadline_miss_pct:4.1f}%)")

    # Aggregate statistics
    stats_summary = {}
    metrics_to_stat = [
        ("miss_count", lambda r: r.critical_deadline_misses),
        ("miss_pct", lambda r: r.critical_deadline_miss_pct),
        ("crit_p50", lambda r: r.critical_p50_us),
        ("crit_p95", lambda r: r.critical_p95_us),
        ("crit_p99", lambda r: r.critical_p99_us),
        ("crit_p99_9", lambda r: r.critical_p99_9_us),
        ("crit_max", lambda r: r.critical_max_us),
        ("throughput", lambda r: r.throughput_mb_s)
    ]

    for name in run_records:
        stats_summary[name] = {}
        for m_key, extractor in metrics_to_stat:
            vals = np.array([extractor(r) for r in run_records[name]])
            n = len(vals)
            mean_val = float(np.mean(vals))
            median_val = float(np.median(vals))
            std_val = float(np.std(vals, ddof=1)) if n > 1 else 0.0
            sem = std_val / np.sqrt(n) if n > 1 else 0.0
            ci95 = T_CRIT_95_DF4 * sem

            stats_summary[name][m_key] = {
                "mean": mean_val,
                "median": median_val,
                "std": std_val,
                "ci95": ci95,
                "ci95_low": mean_val - ci95,
                "ci95_high": mean_val + ci95,
                "raw_runs": vals.tolist()
            }

    print_statistical_tables(stats_summary)

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "statistical_summary.json")
    with open(out_file, "w") as f:
        json.dump(stats_summary, f, indent=2)
    print(f"Complete statistical summary saved to {out_file}")

    return stats_summary

def print_statistical_tables(stats: Dict[str, Any]):
    print("\n" + "=" * 125)
    print("STATISTICAL RESULTS OVER 5 INDEPENDENT TRACE WINDOWS (MEAN +/- 95% CONFIDENCE INTERVAL)")
    print("=" * 125)
    
    # Table 1: Deadline Misses & Throughput
    print("\nTable 1: Deadline Compliance (Slack = 800 us, Background = 200 IOPS)")
    print(f"{'Scheduler':<18} | {'Miss Count (Mean +/- CI)':<28} | {'Miss % (Mean +/- CI)':<25} | {'Miss % (Median +/- Std)':<25} | {'Throughput (MB/s)':<20}")
    print("-" * 125)
    for name, s in stats.items():
        cnt = s["miss_count"]
        pct = s["miss_pct"]
        tp = s["throughput"]
        cnt_str = f"{cnt['mean']:.1f} +/- {cnt['ci95']:.1f}"
        pct_str = f"{pct['mean']:.2f}% +/- {pct['ci95']:.2f}%"
        med_str = f"{pct['median']:.2f}% (std {pct['std']:.2f}%)"
        tp_str = f"{tp['mean']:.1f} +/- {tp['ci95']:.1f}"
        print(f"{name:<18} | {cnt_str:<28} | {pct_str:<25} | {med_str:<25} | {tp_str:<20}")

    # Table 2: Latency Percentiles (P50, P95, P99, P99.9, Max)
    print("\nTable 2: Critical AI Request Latency Percentiles (Microseconds)")
    print(f"{'Scheduler':<18} | {'P50 (Mean +/- CI)':<20} | {'P95 (Mean +/- CI)':<22} | {'P99 (Mean +/- CI)':<22} | {'P99.9 (Mean +/- CI)':<22} | {'Max Latency':<16}")
    print("-" * 125)
    for name, s in stats.items():
        p50 = s["crit_p50"]
        p95 = s["crit_p95"]
        p99 = s["crit_p99"]
        p999 = s["crit_p99_9"]
        mmax = s["crit_max"]
        
        p50_str = f"{p50['mean']:.1f} +/- {p50['ci95']:.1f}"
        p95_str = f"{p95['mean']:.1f} +/- {p95['ci95']:.1f}"
        p99_str = f"{p99['mean']:.1f} +/- {p99['ci95']:.1f}"
        p999_str = f"{p999['mean']:.1f} +/- {p999['ci95']:.1f}"
        max_str = f"{mmax['mean']:.1f} +/- {mmax['ci95']:.1f}"
        
        print(f"{name:<18} | {p50_str:<20} | {p95_str:<22} | {p99_str:<22} | {p999_str:<22} | {max_str:<16}")
    print("=" * 125 + "\n")

if __name__ == "__main__":
    run_multirun_statistical_analysis()
