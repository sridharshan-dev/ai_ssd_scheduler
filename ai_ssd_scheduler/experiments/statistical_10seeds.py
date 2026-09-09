"""Phase 9: 10-Seed Paired Statistical Rigor Analysis.

Runs 10 paired random seeds on the canonical configuration:
- 1500 requests, Slack = 800 us, BG = 200 IOPS with Poisson jitter, QD = 32
- Evaluates S1 (AI-Priority) vs S3 (TEMPO) on identical seeds
- Reports: Mean, Median, Std, 95% CI (t_crit = 2.262 for df=9), Min, Max
"""

import copy
import json
import os
import numpy as np
from typing import List, Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

T_CRIT_95_DF9 = 2.262

def run_10seeds_analysis():
    seeds = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    num_requests = 1500
    skip_initial = 67800
    slack_us = 800.0
    bg_iops = 200.0
    qd = 32

    print("=" * 125)
    print("PHASE 9: 10-SEED PAIRED STATISTICAL RIGOR EVALUATION")
    print(f"Seeds ({len(seeds)}): {seeds} | Slack = {slack_us} us | BG = {bg_iops} IOPS | QD = {qd}")
    print("=" * 125)

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=slack_us
    )

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)

    records_s1 = {"miss_count": [], "miss_pct": [], "p50": [], "p95": [], "p99": [], "p99_9": [], "tput": []}
    records_s3 = {"miss_count": [], "miss_pct": [], "p50": [], "p95": [], "p99": [], "p99_9": [], "tput": []}

    print(f"{'Seed':<6} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'P95 Win':<10}")
    print("-" * 105)

    for seed in seeds:
        np.random.seed(seed)
        reqs = WorkloadGenerator.inject_background_traffic(
            base_slice,
            background_rate_iops=bg_iops,
            jitter=True
        )

        # Run S1
        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(reqs), AIPriorityScheduler())

        # Run S3 (Identical seed and requests)
        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(reqs), AIAndSSDStateScheduler())

        records_s1["miss_count"].append(res_s1.critical_deadline_misses)
        records_s1["miss_pct"].append(res_s1.critical_deadline_miss_pct)
        records_s1["p50"].append(res_s1.critical_p50_us)
        records_s1["p95"].append(res_s1.critical_p95_us)
        records_s1["p99"].append(res_s1.critical_p99_us)
        records_s1["p99_9"].append(res_s1.critical_p99_9_us)
        records_s1["tput"].append(res_s1.throughput_mb_s)

        records_s3["miss_count"].append(res_s3.critical_deadline_misses)
        records_s3["miss_pct"].append(res_s3.critical_deadline_miss_pct)
        records_s3["p50"].append(res_s3.critical_p50_us)
        records_s3["p95"].append(res_s3.critical_p95_us)
        records_s3["p99"].append(res_s3.critical_p99_us)
        records_s3["p99_9"].append(res_s3.critical_p99_9_us)
        records_s3["tput"].append(res_s3.throughput_mb_s)

        delta = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
        p95_win = res_s1.critical_p95_us - res_s3.critical_p95_us
        p95_win_str = f"{p95_win:6.1f} us"
        print(f"{seed:<6} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {p95_win_str:<10}")

    def calc_stats(arr):
        v = np.array(arr)
        mean_v = float(np.mean(v))
        med_v = float(np.median(v))
        std_v = float(np.std(v, ddof=1))
        ci95 = T_CRIT_95_DF9 * (std_v / np.sqrt(len(v)))
        return {
            "mean": round(mean_v, 2),
            "median": round(med_v, 2),
            "std": round(std_v, 2),
            "ci95": round(ci95, 2),
            "min": round(float(np.min(v)), 2),
            "max": round(float(np.max(v)), 2)
        }

    stats_s1 = {k: calc_stats(v) for k, v in records_s1.items()}
    stats_s3 = {k: calc_stats(v) for k, v in records_s3.items()}

    print("\n" + "=" * 125)
    print("PAIRED STATISTICAL SUMMARY (10 SEEDS, N=10, df=9, t_crit=2.262)")
    print("=" * 125)
    print(f"{'Metric':<18} | {'S1 (AI-Priority) Mean +/- CI':<32} | {'S3 (TEMPO) Mean +/- CI':<32} | {'S1 [Min, Max]':<18} | {'S3 [Min, Max]':<18}")
    print("-" * 125)

    for metric in ["miss_pct", "miss_count", "p50", "p95", "p99", "p99_9", "tput"]:
        s1_s = f"{stats_s1[metric]['mean']} +/- {stats_s1[metric]['ci95']}"
        s3_s = f"{stats_s3[metric]['mean']} +/- {stats_s3[metric]['ci95']}"
        s1_rng = f"[{stats_s1[metric]['min']}, {stats_s1[metric]['max']}]"
        s3_rng = f"[{stats_s3[metric]['min']}, {stats_s3[metric]['max']}]"
        print(f"{metric:<18} | {s1_s:<32} | {s3_s:<32} | {s1_rng:<18} | {s3_rng:<18}")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "statistical_10seeds.json")
    with open(out_file, "w") as f:
        json.dump({"s1": stats_s1, "s3": stats_s3, "raw_s1": records_s1, "raw_s3": records_s3}, f, indent=2)
    print(f"\n10-seed statistical report written to {out_file}")

if __name__ == "__main__":
    run_10seeds_analysis()
