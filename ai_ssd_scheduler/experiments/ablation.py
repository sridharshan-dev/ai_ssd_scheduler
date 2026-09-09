"""Phase 9: Ablation Study.

Deconstructs TEMPO (S3) to isolate the marginal contribution of each SSD state signal:
- S1: AI Urgency Only
- S3a: AI Urgency + Channel Readiness (Bus & sensing availability)
- S3b: AI Urgency + Channel Queue Depth (Contention / load-balancing)
- S3c: AI Urgency + GC State (Long erase pause evasion)
- S3-Comb: AI Urgency + Channel Readiness + Queue Depth
- S3-Full: AI Urgency + Channel Readiness + Queue Depth + GC State
"""

import copy
import json
import os
import numpy as np
from typing import List, Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ablation import AblationScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_ablation_study():
    num_requests = 1500
    skip_initial = 67800
    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)

    # -------------------------------------------------------------
    # SCENARIO A: WRITE CONTENTION ABLATION (Slack=800us, BG=200 IOPS, GC=0)
    # Isolates Channel Readiness vs Queue Contention
    # -------------------------------------------------------------
    print("=" * 115)
    print("PHASE 9A: ABLATION STUDY - RUNTIME WRITE CONTENTION (GC = 0)")
    print("Workload: 1500 requests, Slack = 800 us, BG = 200 IOPS, QD = 32")
    print("=" * 115)

    base_reqs_a = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=800.0
    )
    base_reqs_a = WorkloadGenerator.inject_background_traffic(base_reqs_a, background_rate_iops=200.0)

    configs_a = [
        ("S1", "AI Urgency Only", AblationScheduler("S1", True, False, False, False)),
        ("S3a", "AI Urgency + Channel Readiness", AblationScheduler("S3a", True, True, False, False)),
        ("S3b", "AI Urgency + Queue Depth", AblationScheduler("S3b", True, False, True, False)),
        ("S3-Comb", "AI Urgency + ChanReady + QueueDepth", AblationScheduler("S3-Comb", True, True, True, False)),
        ("S3-Native", "TEMPO Native Reference", AIAndSSDStateScheduler())
    ]

    print(f"{'Config ID':<10} | {'Signals Included':<38} | {'Miss %':<8} | {'Miss Delta':<12} | {'P95 (us)':<10} | {'P99 (us)':<10} | {'P99.9 (us)':<11}")
    print("-" * 115)

    results_a = []
    s1_miss_a = 0.0
    for cid, name, sched in configs_a:
        sim = Simulator(config=cfg, max_in_flight=32)
        res = sim.run(copy.deepcopy(base_reqs_a), sched)
        if cid == "S1":
            s1_miss_a = res.critical_deadline_miss_pct

        delta_miss = s1_miss_a - res.critical_deadline_miss_pct
        pct_imp = (delta_miss / s1_miss_a * 100.0) if s1_miss_a > 0 else 0.0

        row = {
            "id": cid,
            "name": name,
            "miss_pct": round(res.critical_deadline_miss_pct, 2),
            "miss_reduction_pct": round(pct_imp, 1),
            "p50_us": round(res.critical_p50_us, 1),
            "p95_us": round(res.critical_p95_us, 1),
            "p99_us": round(res.critical_p99_us, 1),
            "p99_9_us": round(res.critical_p99_9_us, 1)
        }
        results_a.append(row)
        delta_str = f"-{delta_miss:.1f}% ({pct_imp:.0f}%)" if cid != "S1" else "Baseline"
        print(f"{cid:<10} | {name:<38} | {res.critical_deadline_miss_pct:<8.1f} | {delta_str:<12} | {res.critical_p95_us:<10.1f} | {res.critical_p99_us:<10.1f} | {res.critical_p99_9_us:<11.1f}")

    total_imp_a = results_a[0]["miss_pct"] - results_a[3]["miss_pct"]
    print("\n--- SIGNAL ATTRIBUTION IN SCENARIO A (Write Contention) ---")
    print(f"Total Miss Reduction (S1 -> S3-Comb): {results_a[0]['miss_pct']:.1f}% -> {results_a[3]['miss_pct']:.1f}% (Delta = {total_imp_a:.1f}%)")
    for idx in [1, 2, 3]:
        item = results_a[idx]
        delta = results_a[0]["miss_pct"] - item["miss_pct"]
        share = (delta / total_imp_a * 100.0) if total_imp_a > 0 else 0.0
        print(f"  * {item['id']:<8} ({item['name']}): Delta Miss = -{delta:.1f}% -> Accounts for {share:.1f}% of improvement")

    # -------------------------------------------------------------
    # SCENARIO B: ACTIVE GC ERASE CONTENTION (Slack=1200us, BG=200 IOPS, GC=2 x 3.5ms erases)
    # Isolates Channel Readiness vs GC State Awareness
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("PHASE 9B: ABLATION STUDY - ACTIVE GC INTERFERENCE (GC Erase = 2 x 3.5ms)")
    print("Workload: 1500 requests, Slack = 1200 us, BG = 200 IOPS, QD = 32")
    print("=" * 115)

    base_reqs_b = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=1200.0
    )
    base_reqs_b = WorkloadGenerator.inject_background_traffic(base_reqs_b, background_rate_iops=200.0)

    # Inject 2 GC events
    t_start = base_reqs_b[0].arrival_time_us
    t_end = base_reqs_b[-1].arrival_time_us
    dur = t_end - t_start
    gc_events_b = [
        (t_start + 0.33 * dur, 2, 0, 3500.0),
        (t_start + 0.66 * dur, 5, 1, 3500.0)
    ]

    configs_b = [
        ("S1", "AI Urgency Only", AblationScheduler("S1", True, False, False, False)),
        ("S3a", "AI Urgency + Channel Readiness", AblationScheduler("S3a", True, True, False, False)),
        ("S3c", "AI Urgency + GC State", AblationScheduler("S3c", True, False, False, True)),
        ("S3-Full", "AI Urgency + ChanReady + QD + GC", AblationScheduler("S3-Full", True, True, True, True)),
        ("S3-Native", "TEMPO Native Reference", AIAndSSDStateScheduler())
    ]

    print(f"{'Config ID':<10} | {'Signals Included':<38} | {'Miss %':<8} | {'Miss Delta':<12} | {'P95 (us)':<10} | {'P99 (us)':<10} | {'P99.9 (us)':<11}")
    print("-" * 115)

    results_b = []
    s1_miss_b = 0.0
    for cid, name, sched in configs_b:
        sim = Simulator(config=cfg, max_in_flight=32)
        res = sim.run(copy.deepcopy(base_reqs_b), sched, gc_events=gc_events_b)
        if cid == "S1":
            s1_miss_b = res.critical_deadline_miss_pct

        delta_miss = s1_miss_b - res.critical_deadline_miss_pct
        pct_imp = (delta_miss / s1_miss_b * 100.0) if s1_miss_b > 0 else 0.0

        row = {
            "id": cid,
            "name": name,
            "miss_pct": round(res.critical_deadline_miss_pct, 2),
            "miss_reduction_pct": round(pct_imp, 1),
            "p50_us": round(res.critical_p50_us, 1),
            "p95_us": round(res.critical_p95_us, 1),
            "p99_us": round(res.critical_p99_us, 1),
            "p99_9_us": round(res.critical_p99_9_us, 1)
        }
        results_b.append(row)
        delta_str = f"-{delta_miss:.1f}% ({pct_imp:.0f}%)" if cid != "S1" else "Baseline"
        print(f"{cid:<10} | {name:<38} | {res.critical_deadline_miss_pct:<8.1f} | {delta_str:<12} | {res.critical_p95_us:<10.1f} | {res.critical_p99_us:<10.1f} | {res.critical_p99_9_us:<11.1f}")

    total_imp_b = results_b[0]["miss_pct"] - results_b[3]["miss_pct"]
    print("\n--- SIGNAL ATTRIBUTION IN SCENARIO B (GC Interference) ---")
    print(f"Total Miss Reduction (S1 -> S3-Full): {results_b[0]['miss_pct']:.1f}% -> {results_b[3]['miss_pct']:.1f}% (Delta = {total_imp_b:.1f}%)")
    for idx in [1, 2, 3]:
        item = results_b[idx]
        delta = results_b[0]["miss_pct"] - item["miss_pct"]
        share = (delta / total_imp_b * 100.0) if total_imp_b > 0 else 0.0
        print(f"  * {item['id']:<8} ({item['name']}): Delta Miss = -{delta:.1f}% -> Accounts for {share:.1f}% of improvement")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "ablation_analysis.json")
    with open(out_file, "w") as f:
        json.dump({"scenario_a_write_contention": results_a, "scenario_b_gc_interference": results_b}, f, indent=2)
    print(f"\nComplete ablation results successfully written to {out_file}")

if __name__ == "__main__":
    run_ablation_study()
