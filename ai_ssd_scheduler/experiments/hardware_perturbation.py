"""Phase 8: Systematic Hardware Parameter Perturbation (+-10%, +-20%).

Evaluates whether TEMPO's advantage is robust or an artifact of a specific timing parameter.
Perturbs:
1. tR: 36 us +- 10%, +- 20% -> [28.8, 32.4, 36.0, 39.6, 43.2] us
2. tPROG: 185 us +- 10%, +- 20% -> [148.0, 166.5, 185.0, 203.5, 222.0] us
3. tBERS: 3.5 ms +- 10%, +- 20% -> [2.8, 3.15, 3.5, 3.85, 4.2] ms
"""

import copy
import json
import os
from typing import List, Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_hardware_perturbations():
    print("=" * 120)
    print("PHASE 8: SYSTEMATIC HARDWARE PARAMETER PERTURBATION (-20% to +20%)")
    print("Evaluating robustness against parameter variations around nominal Samsung 970 Pro baseline")
    print("=" * 120)

    num_requests = 1500
    skip_initial = 67800
    slack_us = 800.0
    bg_iops = 200.0
    qd = 32

    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=slack_us
    )
    base_slice_bg = WorkloadGenerator.inject_background_traffic(base_slice, background_rate_iops=bg_iops, jitter=False)

    pert_pcts = [-20, -10, 0, 10, 20]
    results = {}

    # 1. Perturb tR (Read sensing latency)
    print("\n[Sweep 8A: NAND Read Latency (tR) Perturbation]")
    print(f"{'Variation':<12} | {'tR (us)':<10} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13}")
    print("-" * 95)
    tr_nominal = 36.0
    tr_results = []
    for p in pert_pcts:
        tr_val = tr_nominal * (1.0 + p / 100.0)
        cfg = SSDConfig(t_read_us=tr_val, t_prog_us=185.0)
        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(base_slice_bg), AIPriorityScheduler())
        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(base_slice_bg), AIAndSSDStateScheduler())
        delta = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
        row = {"pert_pct": p, "val": round(tr_val, 1), "s1_miss": round(res_s1.critical_deadline_miss_pct, 2), "s3_miss": round(res_s3.critical_deadline_miss_pct, 2), "delta": round(delta, 2)}
        tr_results.append(row)
        var_str = f"{p:+d}%" if p != 0 else "Nominal"
        print(f"{var_str:<12} | {tr_val:<10.1f} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f}")
    results["tr_perturbation"] = tr_results

    # 2. Perturb tPROG (Write program latency)
    print("\n[Sweep 8B: NAND Program Latency (tPROG) Perturbation]")
    print(f"{'Variation':<12} | {'tPROG (us)':<10} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13}")
    print("-" * 95)
    tp_nominal = 185.0
    tp_results = []
    for p in pert_pcts:
        tp_val = tp_nominal * (1.0 + p / 100.0)
        cfg = SSDConfig(t_read_us=36.0, t_prog_us=tp_val)
        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(base_slice_bg), AIPriorityScheduler())
        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(base_slice_bg), AIAndSSDStateScheduler())
        delta = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
        row = {"pert_pct": p, "val": round(tp_val, 1), "s1_miss": round(res_s1.critical_deadline_miss_pct, 2), "s3_miss": round(res_s3.critical_deadline_miss_pct, 2), "delta": round(delta, 2)}
        tp_results.append(row)
        var_str = f"{p:+d}%" if p != 0 else "Nominal"
        print(f"{var_str:<12} | {tp_val:<10.1f} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f}")
    results["tprog_perturbation"] = tp_results

    # 3. Perturb tBERS (Block Erase Latency under GC)
    print("\n[Sweep 8C: GC Block Erase Latency (tBERS) Perturbation]")
    print(f"{'Variation':<12} | {'tBERS (ms)':<10} | {'S1 P99 (us)':<13} | {'S3 P99 (us)':<13} | {'P99 Win':<12} | {'S1 P99.9 (us)':<14} | {'S3 P99.9 (us)':<14}")
    print("-" * 95)
    tb_nominal = 3500.0 # us
    tb_results = []
    t_start = base_slice_bg[0].arrival_time_us
    t_end = base_slice_bg[-1].arrival_time_us
    dur = t_end - t_start
    
    for p in pert_pcts:
        tb_val_us = tb_nominal * (1.0 + p / 100.0)
        tb_ms = tb_val_us / 1000.0
        gc_events = [
            (t_start + 0.33 * dur, 2, 0, tb_val_us),
            (t_start + 0.66 * dur, 5, 1, tb_val_us)
        ]
        cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
        sim_s1 = Simulator(config=cfg, max_in_flight=qd)
        res_s1 = sim_s1.run(copy.deepcopy(base_slice_bg), AIPriorityScheduler(), gc_events=gc_events)
        sim_s3 = Simulator(config=cfg, max_in_flight=qd)
        res_s3 = sim_s3.run(copy.deepcopy(base_slice_bg), AIAndSSDStateScheduler(), gc_events=gc_events)
        p99_win = res_s1.critical_p99_us - res_s3.critical_p99_us
        p999_win = res_s1.critical_p99_9_us - res_s3.critical_p99_9_us
        row = {"pert_pct": p, "val_ms": round(tb_ms, 2), "s1_p99": round(res_s1.critical_p99_us, 1), "s3_p99": round(res_s3.critical_p99_us, 1), "p99_win": round(p99_win, 1)}
        tb_results.append(row)
        var_str = f"{p:+d}%" if p != 0 else "Nominal"
        p99_win_str = f"{p99_win:6.1f} us"
        print(f"{var_str:<12} | {tb_ms:<10.2f} | {res_s1.critical_p99_us:<13.1f} | {res_s3.critical_p99_us:<13.1f} | {p99_win_str:<12} | {res_s1.critical_p99_9_us:<14.1f} | {res_s3.critical_p99_9_us:<14.1f}")
    results["tbers_perturbation"] = tb_results

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "hardware_perturbation.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nHardware perturbation data written to {out_file}")

if __name__ == "__main__":
    run_hardware_perturbations()
