"""Phase 2: AI Urgency x SSD Contention Matrix (Multi-Seed).

Evaluates S1 (AI-Priority) vs S3 (TEMPO) across 9 background load levels:
[0, 50, 100, 200, 300, 500, 800, 1200, 1600] IOPS
with 5 genuine random seeds generating Poisson exponential inter-arrival jitter.
"""

import copy
import json
import os
from typing import List, Dict, Any
import numpy as np

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_contention_matrix_multiseed():
    num_requests = 1500
    skip_initial = 67800
    slack_us = 800.0
    qd = 32
    bg_loads = [0.0, 50.0, 100.0, 200.0, 300.0, 500.0, 800.0, 1200.0, 1600.0]
    seeds = [42, 123, 456, 789, 999]

    print("=" * 125)
    print("PHASE 2: AI URGENCY x SSD CONTENTION MATRIX (5 SEEDS PER LOAD LEVEL)")
    print(f"Workload: {num_requests} requests | Slack = {slack_us} us | QD = {qd} | BG Loads: {bg_loads}")
    print("=" * 125)

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=slack_us
    )

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    matrix_summary = []

    print(f"{'BG IOPS':<9} | {'S1 Miss % (Mean +/- Std)':<26} | {'S3 Miss % (Mean +/- Std)':<26} | {'Miss Delta':<12} | {'S1 P95 (us)':<14} | {'S3 P95 (us)':<14} | {'P95 Win':<10}")
    print("-" * 125)

    for bg in bg_loads:
        s1_miss_list, s3_miss_list = [], []
        s1_p50_list, s3_p50_list = [], []
        s1_p95_list, s3_p95_list = [], []
        s1_p99_list, s3_p99_list = [], []
        s1_p999_list, s3_p999_list = [], []
        s1_tput_list, s3_tput_list = [], []

        for seed in seeds:
            np.random.seed(seed)
            if bg > 0:
                reqs = WorkloadGenerator.inject_background_traffic(
                    base_slice,
                    background_rate_iops=bg,
                    jitter=True
                )
            else:
                reqs = copy.deepcopy(base_slice)

            # Run S1
            sim_s1 = Simulator(config=cfg, max_in_flight=qd)
            res_s1 = sim_s1.run(copy.deepcopy(reqs), AIPriorityScheduler())
            s1_miss_list.append(res_s1.critical_deadline_miss_pct)
            s1_p50_list.append(res_s1.critical_p50_us)
            s1_p95_list.append(res_s1.critical_p95_us)
            s1_p99_list.append(res_s1.critical_p99_us)
            s1_p999_list.append(res_s1.critical_p99_9_us)
            s1_tput_list.append(res_s1.throughput_mb_s)

            # Run S3
            sim_s3 = Simulator(config=cfg, max_in_flight=qd)
            res_s3 = sim_s3.run(copy.deepcopy(reqs), AIAndSSDStateScheduler())
            s3_miss_list.append(res_s3.critical_deadline_miss_pct)
            s3_p50_list.append(res_s3.critical_p50_us)
            s3_p95_list.append(res_s3.critical_p95_us)
            s3_p99_list.append(res_s3.critical_p99_us)
            s3_p999_list.append(res_s3.critical_p99_9_us)
            s3_tput_list.append(res_s3.throughput_mb_s)

        s1_miss_m, s1_miss_s = float(np.mean(s1_miss_list)), float(np.std(s1_miss_list))
        s3_miss_m, s3_miss_s = float(np.mean(s3_miss_list)), float(np.std(s3_miss_list))
        s1_p95_m, s3_p95_m = float(np.mean(s1_p95_list)), float(np.mean(s3_p95_list))
        delta_miss = s1_miss_m - s3_miss_m
        p95_win = s1_p95_m - s3_p95_m

        row = {
            "bg_iops": bg,
            "s1": {
                "miss_pct_mean": round(s1_miss_m, 2), "miss_pct_std": round(s1_miss_s, 2),
                "p50_mean": round(float(np.mean(s1_p50_list)), 1),
                "p95_mean": round(s1_p95_m, 1),
                "p99_mean": round(float(np.mean(s1_p99_list)), 1),
                "p999_mean": round(float(np.mean(s1_p999_list)), 1),
                "tput_mean": round(float(np.mean(s1_tput_list)), 1)
            },
            "s3": {
                "miss_pct_mean": round(s3_miss_m, 2), "miss_pct_std": round(s3_miss_s, 2),
                "p50_mean": round(float(np.mean(s3_p50_list)), 1),
                "p95_mean": round(s3_p95_m, 1),
                "p99_mean": round(float(np.mean(s3_p99_list)), 1),
                "p999_mean": round(float(np.mean(s3_p999_list)), 1),
                "tput_mean": round(float(np.mean(s3_tput_list)), 1)
            },
            "delta_miss": round(delta_miss, 2),
            "p95_win_us": round(p95_win, 1)
        }
        matrix_summary.append(row)

        s1_str = f"{s1_miss_m:5.1f}% +/- {s1_miss_s:4.1f}%"
        s3_str = f"{s3_miss_m:5.1f}% +/- {s3_miss_s:4.1f}%"
        p95_win_str = f"{p95_win:6.1f} us"
        print(f"{bg:<9.0f} | {s1_str:<26} | {s3_str:<26} | {delta_miss:<12.1f} | {s1_p95_m:<14.1f} | {s3_p95_m:<14.1f} | {p95_win_str:<10}")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "contention_matrix_multiseed.json")
    with open(out_file, "w") as f:
        json.dump(matrix_summary, f, indent=2)
    print(f"\nMatrix results written to {out_file}")

if __name__ == "__main__":
    run_contention_matrix_multiseed()
