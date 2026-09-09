"""Phase 5: High-Resolution Crossover Point Discovery."""

import copy
import json
import os
import time
from typing import List, Dict, Any
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def find_crossover_curve(
    num_requests: int = 1500,
    skip_initial: int = 67800,
    bg_iops: float = 200.0,
    qd: int = 32,
    fine_slacks: List[float] = [
        500.0, 600.0, 650.0, 700.0, 750.0, 800.0, 850.0, 900.0, 950.0,
        1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1750.0, 2000.0
    ]
):
    print("=" * 110)
    print("PHASE 5: HIGH-RESOLUTION CROSSOVER ANALYSIS (S1 vs. S3)")
    print(f"Testing {len(fine_slacks)} deadline points between 500 us and 2000 us")
    print(f"Fixed parameters: Requests={num_requests}, Background={bg_iops} IOPS, QD={qd}")
    print("=" * 110)

    raw_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=1200.0
    )
    if bg_iops > 0:
        raw_slice = WorkloadGenerator.inject_background_traffic(raw_slice, background_rate_iops=bg_iops)

    results = []

    print(f"\n{'Slack (us)':<10} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Delta (%)':<12} | {'Miss Ratio (S1/S3)':<20} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'Regime':<18}")
    print("-" * 115)

    for slack in fine_slacks:
        # Re-annotate slice with current slack
        reqs = copy.deepcopy(raw_slice)
        for r in reqs:
            if r.priority.name == "CRITICAL":
                r.deadline_us = r.arrival_time_us + slack

        # Run S1
        sim_s1 = Simulator(config=SSDConfig(), max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(reqs), AIPriorityScheduler())

        # Run S3
        sim_s3 = Simulator(config=SSDConfig(), max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(reqs), AIAndSSDStateScheduler())

        delta_miss = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
        
        if res_s3.critical_deadline_miss_pct > 0.0:
            ratio_str = f"{res_s1.critical_deadline_miss_pct / res_s3.critical_deadline_miss_pct:.2f}x"
        else:
            ratio_str = "INF (S3=0)" if res_s1.critical_deadline_miss_pct > 0 else "1.00x (both 0)"

        # Classify regime
        if slack <= 600.0:
            regime = "Physics Floor"
        elif delta_miss >= 10.0:
            regime = "S3 >> S1 (Major Win)"
        elif delta_miss >= 2.0:
            regime = "S3 > S1 (Modest Win)"
        elif abs(delta_miss) < 2.0 and res_s1.critical_deadline_miss_pct > 0:
            regime = "S3 ~ S1 (Transition)"
        else:
            regime = "S3 ~ S1 (Parity/Idle)"

        row = {
            "slack_us": slack,
            "s1_miss_pct": res_s1.critical_deadline_miss_pct,
            "s3_miss_pct": res_s3.critical_deadline_miss_pct,
            "delta_miss": delta_miss,
            "ratio_str": ratio_str,
            "s1_p95": res_s1.critical_p95_us,
            "s3_p95": res_s3.critical_p95_us,
            "regime": regime
        }
        results.append(row)

        print(f"{slack:<10.0f} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta_miss:<12.1f} | {ratio_str:<20} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {regime:<18}")

    print("-" * 115)
    
    out_file = os.path.join("results", "crossover_curve.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nCrossover results saved to {out_file}")
    return results

if __name__ == "__main__":
    find_crossover_curve()
