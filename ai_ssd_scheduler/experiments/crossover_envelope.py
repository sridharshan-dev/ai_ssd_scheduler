"""Phase 3: High-Resolution Crossover & Operating Envelope Discovery.

Sweeps deadline slacks:
[500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400, 1500, 1600, 1800, 2000] us
at Fixed BG = 200 IOPS, QD = 32.
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

def run_crossover_envelope():
    num_requests = 1500
    skip_initial = 67800
    bg_iops = 200.0
    qd = 32
    slacks = [500.0, 600.0, 700.0, 800.0, 900.0, 1000.0, 1100.0, 1200.0, 1300.0, 1400.0, 1500.0, 1600.0, 1800.0, 2000.0]

    print("=" * 125)
    print("PHASE 3: OPERATING ENVELOPE DISCOVERY (DEADLINE CROSSOVER SWEEP)")
    print(f"Slacks: {slacks} us | Fixed BG: {bg_iops} IOPS | Fixed QD: {qd}")
    print("=" * 125)

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=1200.0
    )
    # Inject background writes once for fixed comparison
    base_slice_bg = WorkloadGenerator.inject_background_traffic(base_slice, background_rate_iops=bg_iops, jitter=False)

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    envelope_results = []

    print(f"{'Slack (us)':<11} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1/S3 Ratio':<14} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'Operating Regime':<20}")
    print("-" * 125)

    for slack in slacks:
        reqs = copy.deepcopy(base_slice_bg)
        for r in reqs:
            if r.priority.name == "CRITICAL":
                r.deadline_us = r.arrival_time_us + slack

        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(reqs), AIPriorityScheduler())

        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(reqs), AIAndSSDStateScheduler())

        s1_miss = res_s1.critical_deadline_miss_pct
        s3_miss = res_s3.critical_deadline_miss_pct
        delta = s1_miss - s3_miss
        ratio = (s1_miss / s3_miss) if s3_miss > 0 else (999.0 if s1_miss > 0 else 1.0)
        ratio_str = f"{ratio:.2f}x" if ratio < 100.0 else "Inf"

        # Classify regime
        if slack <= 650.0:
            regime = "Physical Floor (S3 ~ S1)"
        elif slack <= 900.0:
            regime = "Peak Advantage (S3 >> S1)"
        elif slack <= 1400.0:
            regime = "Tail Smoothing (S3 > S1)"
        else:
            regime = "Slack Parity (S3 ~ S1)"

        row = {
            "slack_us": slack,
            "s1_miss_pct": round(s1_miss, 2),
            "s3_miss_pct": round(s3_miss, 2),
            "delta_miss": round(delta, 2),
            "s1_p95_us": round(res_s1.critical_p95_us, 1),
            "s3_p95_us": round(res_s3.critical_p95_us, 1),
            "regime": regime
        }
        envelope_results.append(row)

        print(f"{slack:<11.0f} | {s1_miss:<12.1f} | {s3_miss:<12.1f} | {delta:<12.1f} | {ratio_str:<14} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {regime:<20}")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "crossover_envelope.json")
    with open(out_file, "w") as f:
        json.dump(envelope_results, f, indent=2)
    print(f"\nOperating envelope data saved to {out_file}")

if __name__ == "__main__":
    run_crossover_envelope()
