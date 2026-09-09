"""Phase 11: Defensible SSD Energy Evaluation across S0, S1, S2, and S3.

Calculates:
- Total Energy (Joules)
- Energy / Request (mJ)
- Energy / MB (mJ / MB)
- Energy / Deadline-Satisfied AI Request (mJ / successful critical req)
"""

import copy
import json
import os
from typing import Dict, Any

from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..ssd.energy import SSDEnergyModel
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_energy_evaluation():
    num_requests = 1500
    skip_initial = 67800
    deadline_slack_us = 800.0
    bg_iops = 200.0

    print("=" * 115)
    print("PHASE 11: DEFENSIBLE SSD ENERGY EVALUATION")
    print(f"Workload: {num_requests} requests from CHEOPS KV-cache trace, Slack = {deadline_slack_us} us, BG = {bg_iops} IOPS")
    print("Power Model: Samsung 970 Pro (Read: 5.2 W, Write: 5.7 W, Standby: 0.5 W)")
    print("=" * 115)

    base_reqs = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=0.4,
        deadline_slack_us=deadline_slack_us
    )
    base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=bg_iops)

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    energy_model = SSDEnergyModel()

    schedulers = [
        ("S0-FIFO", FIFOScheduler()),
        ("S1-AI-Priority", AIPriorityScheduler()),
        ("S2-SSD-State", SSDStateScheduler()),
        ("S3-AI+SSD-State (TEMPO)", AIAndSSDStateScheduler())
    ]

    results = []

    print(f"{'Scheduler':<24} | {'Total J':<9} | {'mJ/Req':<8} | {'mJ/MB':<8} | {'Critical Met':<14} | {'Miss %':<8} | {'mJ / Satisfied AI Req':<22}")
    print("-" * 115)

    for name, sched in schedulers:
        sim = Simulator(config=cfg, max_in_flight=32)
        res = sim.run(copy.deepcopy(base_reqs), sched)

        # Compute duration of execution
        duration_us = res.elapsed_time_ms * 1000.0
        energy_prof = energy_model.compute_energy(sim.completed_requests, duration_us)

        row = {
            "scheduler": name,
            "total_joules": energy_prof.total_energy_joules,
            "mj_per_request": energy_prof.energy_per_request_mj,
            "mj_per_mb": energy_prof.energy_per_mb_mj,
            "satisfied_critical_count": energy_prof.satisfied_critical_count,
            "total_critical_count": energy_prof.total_critical_count,
            "miss_pct": round(res.critical_deadline_miss_pct, 2),
            "mj_per_satisfied_req": energy_prof.energy_per_satisfied_critical_req_mj
        }
        results.append(row)

        met_str = f"{energy_prof.satisfied_critical_count} / {energy_prof.total_critical_count}"
        print(f"{name:<24} | {energy_prof.total_energy_joules:<9.4f} | {energy_prof.energy_per_request_mj:<8.3f} | {energy_prof.energy_per_mb_mj:<8.3f} | {met_str:<14} | {res.critical_deadline_miss_pct:<8.1f} | {energy_prof.energy_per_satisfied_critical_req_mj:<22.3f}")

    # Compute key comparative ratio
    s1_mj_sat = results[1]["mj_per_satisfied_req"]
    s3_mj_sat = results[3]["mj_per_satisfied_req"]
    energy_eff_gain = ((s1_mj_sat - s3_mj_sat) / s1_mj_sat) * 100.0

    print("\n" + "=" * 115)
    print("KEY RESEARCH FINDING ON ENERGY EFFICIENCY:")
    print("=" * 115)
    print(f"Total raw energy between S1 and S3 is comparable ({results[1]['total_joules']:.3f} J vs {results[3]['total_joules']:.3f} J) because the same physical bytes are transferred.")
    print(f"HOWEVER, in the crucial metric 'Energy per Deadline-Satisfied AI Request':")
    print(f"  * S1 (AI-Priority): {s1_mj_sat:.3f} mJ / satisfied request ({results[1]['satisfied_critical_count']} met deadlines)")
    print(f"  * S3 (TEMPO):       {s3_mj_sat:.3f} mJ / satisfied request ({results[3]['satisfied_critical_count']} met deadlines)")
    print(f"  --> TEMPO achieves a {energy_eff_gain:.1f}% reduction in Energy per Deadline-Satisfied AI Request!")
    print(f"  --> S1 expends 'wasted energy' on {results[1]['total_critical_count'] - results[1]['satisfied_critical_count']} requests that violated the SLA and produced pipeline stalls.")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "energy_evaluation.json")
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nEnergy evaluation written to {out_file}")

if __name__ == "__main__":
    run_energy_evaluation()
