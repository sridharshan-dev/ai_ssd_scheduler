"""Phase 6: Fine-Grained Queue Depth Curve (Verifying Bufferbloat Knee).

Sweeps Queue Depth: [8, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64]
at Slack = 800 us, BG = 200 IOPS.
Identifies the critical knee where hardware queue over-commitment locks channels.
"""

import copy
import json
import os
from typing import List, Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_qd_curve():
    num_requests = 1500
    skip_initial = 67800
    slack_us = 800.0
    bg_iops = 200.0
    qd_values = [8, 12, 16, 20, 24, 28, 32, 40, 48, 56, 64]

    print("=" * 120)
    print("PHASE 6: FINE-GRAINED QUEUE DEPTH CURVE (TESTING THE BUFFERBLOAT HYPOTHESIS)")
    print(f"Sweeping QD across {len(qd_values)} points: {qd_values}")
    print(f"Fixed: Slack = {slack_us} us | BG = {bg_iops} IOPS")
    print("=" * 120)

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=slack_us
    )
    base_slice_bg = WorkloadGenerator.inject_background_traffic(base_slice, background_rate_iops=bg_iops, jitter=False)

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    curve_data = []

    print(f"{'QD':<5} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'Operational Phase':<25}")
    print("-" * 120)

    for qd in qd_values:
        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(base_slice_bg), AIPriorityScheduler())

        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(base_slice_bg), AIAndSSDStateScheduler())

        s1_miss = res_s1.critical_deadline_miss_pct
        s3_miss = res_s3.critical_deadline_miss_pct
        delta = s1_miss - s3_miss

        if qd <= 12:
            phase = "Under-concurrency (Low choice)"
        elif qd <= 32:
            phase = "Optimal Window (High S3 win)"
        elif qd <= 48:
            phase = "Incipient Saturation (Knee)"
        else:
            phase = "Bufferbloat / Channel Jam"

        row = {
            "queue_depth": qd,
            "s1_miss_pct": round(s1_miss, 2),
            "s3_miss_pct": round(s3_miss, 2),
            "delta_miss": round(delta, 2),
            "s1_p95_us": round(res_s1.critical_p95_us, 1),
            "s3_p95_us": round(res_s3.critical_p95_us, 1),
            "s1_p99_us": round(res_s1.critical_p99_us, 1),
            "s3_p99_us": round(res_s3.critical_p99_us, 1),
            "phase": phase
        }
        curve_data.append(row)

        print(f"{qd:<5} | {s1_miss:<12.1f} | {s3_miss:<12.1f} | {delta:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {phase:<25}")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "qd_bufferbloat_curve.json")
    with open(out_file, "w") as f:
        json.dump(curve_data, f, indent=2)
    print(f"\nQD Bufferbloat curve written to {out_file}")

if __name__ == "__main__":
    run_qd_curve()
