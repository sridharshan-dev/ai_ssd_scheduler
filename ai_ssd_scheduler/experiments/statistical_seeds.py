"""Multi-Seed Statistical Analysis on Bursty Active Decode Trace."""

import copy
import json
import os
import numpy as np
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

T_CRIT_95_DF4 = 2.776

def run_multiseed_analysis(
    seeds: list = [42, 123, 456, 789, 999],
    num_requests: int = 2000,
    skip_initial: int = 67800,
    critical_fraction: float = 0.4,
    deadline_slack_us: float = 750.0,
    bg_iops: float = 300.0,
    qd: int = 32
):
    print("=" * 115)
    print("MULTI-SEED STATISTICAL ANALYSIS (CONTENDING BURST PHASE)")
    print(f"5 Random Seeds: {seeds} | Slack = {deadline_slack_us} us | BG = {bg_iops} IOPS | QD = {qd}")
    print("=" * 115)

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=critical_fraction,
        deadline_slack_us=deadline_slack_us
    )

    schedulers_factory = [
        ("S0-FIFO", lambda: FIFOScheduler()),
        ("S1-AI-Priority", lambda: AIPriorityScheduler()),
        ("S2-SSD-State", lambda: SSDStateScheduler()),
        ("S3-AI+SSD-State", lambda: AIAndSSDStateScheduler())
    ]

    records = {name: [] for name, _ in schedulers_factory}

    for seed in seeds:
        np.random.seed(seed)
        # Add jittered background writes
        reqs = WorkloadGenerator.inject_background_traffic(
            base_slice,
            background_rate_iops=bg_iops
        )
        for name, factory in schedulers_factory:
            sched = factory()
            sim = Simulator(config=SSDConfig(), max_in_flight=qd)
            res = sim.run(copy.deepcopy(reqs), sched)
            records[name].append(res)
            print(f"Seed {seed:<4} | {name:<18} -> P95: {res.critical_p95_us:6.1f} | P99: {res.critical_p99_us:6.1f} | P99.9: {res.critical_p99_9_us:6.1f} | Misses: {res.critical_deadline_misses:3d} ({res.critical_deadline_miss_pct:4.1f}%)")

    # Aggregate stats
    stats = {}
    for name in records:
        stats[name] = {}
        for metric, ext in [
            ("miss_count", lambda r: r.critical_deadline_misses),
            ("miss_pct", lambda r: r.critical_deadline_miss_pct),
            ("p50", lambda r: r.critical_p50_us),
            ("p95", lambda r: r.critical_p95_us),
            ("p99", lambda r: r.critical_p99_us),
            ("p99_9", lambda r: r.critical_p99_9_us),
            ("max", lambda r: r.critical_max_us),
        ]:
            arr = np.array([ext(r) for r in records[name]])
            mean_v = float(np.mean(arr))
            med_v = float(np.median(arr))
            std_v = float(np.std(arr, ddof=1))
            ci95 = T_CRIT_95_DF4 * (std_v / np.sqrt(len(arr)))
            stats[name][metric] = {
                "mean": mean_v, "median": med_v, "std": std_v, "ci95": ci95
            }

    print("\n" + "=" * 125)
    print("STATISTICAL SUMMARY ACROSS 5 SEEDS (BURST KV-CACHE PHASE)")
    print("=" * 125)
    print(f"{'Scheduler':<18} | {'Miss Count (Mean +/- CI)':<26} | {'Miss % (Mean +/- CI)':<24} | {'P95 (Mean +/- CI)':<22} | {'P99.9 (Mean +/- CI)':<22}")
    print("-" * 125)
    for name, s in stats.items():
        cnt_s = f"{s['miss_count']['mean']:.1f} +/- {s['miss_count']['ci95']:.1f}"
        pct_s = f"{s['miss_pct']['mean']:.2f}% +/- {s['miss_pct']['ci95']:.2f}%"
        p95_s = f"{s['p95']['mean']:.1f} +/- {s['p95']['ci95']:.1f} us"
        p999_s = f"{s['p99_9']['mean']:.1f} +/- {s['p99_9']['ci95']:.1f} us"
        print(f"{name:<18} | {cnt_s:<26} | {pct_s:<24} | {p95_s:<22} | {p999_s:<22}")
    print("=" * 125)

if __name__ == "__main__":
    run_multiseed_analysis()
