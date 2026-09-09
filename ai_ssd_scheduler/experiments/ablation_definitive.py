"""Phase 5: Definitive Ablation Study.

Evaluates the exact contribution of each SSD hardware signal:
- S1: AI Urgency Only
- S3a: AI Urgency + Channel/LUN Readiness (temporal busy timers)
- S3b: AI Urgency + Queue Depth (static load count)
- S3c: AI Urgency + GC State (long block erase detection)
- S3-Full: AI Urgency + Full Predicted Completion (cycle-accurate channel pipelining)

Under both:
1. Write Contention (Slack = 800 us, BG = 200 IOPS)
2. Active GC Interference (Slack = 1200 us, BG = 200 IOPS, GC = 2 x 3.5ms)
"""

import copy
import json
import os
from typing import List, Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ablation import AblationScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_ablation_definitive():
    print("=" * 120)
    print("PHASE 5: DEFINITIVE ABLATION STUDY (ISOLATING HARDWARE STATE SIGNALS)")
    print("=" * 120)

    num_requests = 1500
    skip_initial = 67800
    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)

    # 1. Regime A: Write Contention
    base_slice_a = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=800.0
    )
    base_slice_a = WorkloadGenerator.inject_background_traffic(base_slice_a, background_rate_iops=200.0, jitter=False)

    variants_a = [
        ("S1", "AI Urgency Only", AblationScheduler("S1", True, False, False, False)),
        ("S3a", "+ Channel/LUN Readiness", AblationScheduler("S3a", True, True, False, False)),
        ("S3b", "+ Queue Depth", AblationScheduler("S3b", True, False, True, False)),
        ("S3-Full", "Full TEMPO (Urgency + ChanReady + QD)", AblationScheduler("S3-Full", True, True, True, False)),
        ("S3-Native", "Full Cycle-Accurate Delay Prediction", AIAndSSDStateScheduler())
    ]

    print("\n--- REGIME A: RUNTIME WRITE CONTENTION (Slack = 800 us, BG = 200 IOPS) ---")
    print(f"{'Config':<10} | {'Signal Configuration':<36} | {'Miss %':<8} | {'Miss Delta':<12} | {'P95 (us)':<12} | {'P99 (us)':<12}")
    print("-" * 105)

    results_a = []
    s1_miss_a = 0.0
    for cid, name, sched in variants_a:
        sim = Simulator(config=cfg, max_in_flight=32)
        res = sim.run(copy.deepcopy(base_slice_a), sched)
        if cid == "S1":
            s1_miss_a = res.critical_deadline_miss_pct

        delta = s1_miss_a - res.critical_deadline_miss_pct
        pct_gain = (delta / s1_miss_a * 100.0) if s1_miss_a > 0 else 0.0
        delta_str = f"-{delta:.1f}% ({pct_gain:.0f}%)" if cid != "S1" else "Baseline"

        row = {
            "id": cid, "name": name,
            "miss_pct": round(res.critical_deadline_miss_pct, 2),
            "p50_us": round(res.critical_p50_us, 1),
            "p95_us": round(res.critical_p95_us, 1),
            "p99_us": round(res.critical_p99_us, 1),
            "p99_9_us": round(res.critical_p99_9_us, 1)
        }
        results_a.append(row)
        print(f"{cid:<10} | {name:<36} | {res.critical_deadline_miss_pct:<8.1f} | {delta_str:<12} | {res.critical_p95_us:<12.1f} | {res.critical_p99_us:<12.1f}")

    # 2. Regime B: GC Interference
    base_slice_b = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=1200.0
    )
    base_slice_b = WorkloadGenerator.inject_background_traffic(base_slice_b, background_rate_iops=200.0, jitter=False)

    t_start = base_slice_b[0].arrival_time_us
    t_end = base_slice_b[-1].arrival_time_us
    dur = t_end - t_start
    gc_events_b = [
        (t_start + 0.33 * dur, 2, 0, 3500.0),
        (t_start + 0.66 * dur, 5, 1, 3500.0)
    ]

    variants_b = [
        ("S1", "AI Urgency Only", AblationScheduler("S1", True, False, False, False)),
        ("S3a", "+ Channel/LUN Readiness", AblationScheduler("S3a", True, True, False, False)),
        ("S3c", "+ GC State Awareness", AblationScheduler("S3c", True, False, False, True)),
        ("S3-Full", "Full TEMPO (Urgency + Chan + QD + GC)", AblationScheduler("S3-Full", True, True, True, True)),
        ("S3-Native", "Full Cycle-Accurate Delay Prediction", AIAndSSDStateScheduler())
    ]

    print("\n--- REGIME B: ACTIVE GC INTERFERENCE (Slack = 1200 us, BG = 200 IOPS, GC = 2 x 3.5ms) ---")
    print(f"{'Config':<10} | {'Signal Configuration':<36} | {'Miss %':<8} | {'Miss Delta':<12} | {'P95 (us)':<12} | {'P99 (us)':<12}")
    print("-" * 105)

    results_b = []
    s1_miss_b = 0.0
    for cid, name, sched in variants_b:
        sim = Simulator(config=cfg, max_in_flight=32)
        res = sim.run(copy.deepcopy(base_slice_b), sched, gc_events=gc_events_b)
        if cid == "S1":
            s1_miss_b = res.critical_deadline_miss_pct

        delta = s1_miss_b - res.critical_deadline_miss_pct
        pct_gain = (delta / s1_miss_b * 100.0) if s1_miss_b > 0 else 0.0
        delta_str = f"-{delta:.1f}% ({pct_gain:.0f}%)" if cid != "S1" else "Baseline"

        row = {
            "id": cid, "name": name,
            "miss_pct": round(res.critical_deadline_miss_pct, 2),
            "p50_us": round(res.critical_p50_us, 1),
            "p95_us": round(res.critical_p95_us, 1),
            "p99_us": round(res.critical_p99_us, 1),
            "p99_9_us": round(res.critical_p99_9_us, 1)
        }
        results_b.append(row)
        print(f"{cid:<10} | {name:<36} | {res.critical_deadline_miss_pct:<8.1f} | {delta_str:<12} | {res.critical_p95_us:<12.1f} | {res.critical_p99_us:<12.1f}")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "ablation_definitive.json")
    with open(out_file, "w") as f:
        json.dump({"regime_a_write_contention": results_a, "regime_b_gc_interference": results_b}, f, indent=2)
    print(f"\nDefinitive ablation results written to {out_file}")

if __name__ == "__main__":
    run_ablation_definitive()
