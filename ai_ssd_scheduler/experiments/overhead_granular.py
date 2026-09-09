"""Phase 7: Granular Scheduler Overhead Profiling.

Profiles individual components of TEMPO's decision loop:
1. Candidates examined per dispatch
2. Backend state prediction cost (SRAM reads + earliest ready calculation)
3. Urgency score calculation cost (Priority math + deadline pressure division)
4. Total scheduling decision latency
5. Estimated controller CPU cycles on ARM Cortex-R8 @ 800 MHz
"""

import copy
import json
import math
import os
import time
from typing import List, Dict, Any
import numpy as np

from ..ssd.nand import SSDConfig
from ..ssd.backend import SSDBackend
from ..ssd.request import Request
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

class GranularProfiledTEMPO(AIAndSSDStateScheduler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_decision_ns: List[float] = []
        self.urgency_calc_ns: List[float] = []
        self.state_predict_ns: List[float] = []
        self.candidates_per_dispatch: List[int] = []
        self.sram_lookups_per_dispatch: List[int] = []

    def select_next(self, backend: SSDBackend, now: float):
        if not self.queue:
            return None

        t_start_decision = time.perf_counter_ns()
        q_len = len(self.queue)
        self.candidates_per_dispatch.append(q_len)

        best_idx = 0
        best_score = -1e9
        best_arrival = 1e12

        t_urgency_accum = 0.0
        t_predict_accum = 0.0
        sram_reads = 0

        for i in range(q_len):
            req = self.queue[i]

            # 1. Profile Urgency Score Calculation
            t_u0 = time.perf_counter_ns()
            tier_base = req.priority * self.w_urgency
            deadline_boost = 0.0
            if req.deadline_us > 0.0:
                slack_us = req.deadline_us - now
                if slack_us > 0.0:
                    deadline_boost = self.w_deadline / (slack_us + 10.0)
                else:
                    deadline_boost = self.w_deadline * 5.0 + abs(slack_us)
            urgency_score = tier_base + deadline_boost
            t_u1 = time.perf_counter_ns()
            t_urgency_accum += (t_u1 - t_u0)

            # 2. Profile Hardware Delay Prediction
            t_p0 = time.perf_counter_ns()
            delay_us = backend.estimate_service_delay(req, now)
            t_p1 = time.perf_counter_ns()
            t_predict_accum += (t_p1 - t_p0)

            # SRAM lookups: 2 per sub-page
            sub_count = len(req.sub_pages) if req.sub_pages else 4
            sram_reads += (sub_count * 2)

            score = urgency_score - (self.w_channel_delay * delay_us)

            if score > best_score:
                best_idx = i
                best_score = score
                best_arrival = req.arrival_time_us
            elif abs(score - best_score) < 1e-4 and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        t_end_decision = time.perf_counter_ns()
        self.total_decision_ns.append(t_end_decision - t_start_decision)
        self.urgency_calc_ns.append(t_urgency_accum)
        self.state_predict_ns.append(t_predict_accum)
        self.sram_lookups_per_dispatch.append(sram_reads)

        return self.queue.pop(best_idx)

def run_overhead_profiling():
    print("=" * 120)
    print("PHASE 7: GRANULAR SCHEDULER OVERHEAD PROFILING")
    print("Evaluating component-level timing, SRAM memory access, and ARM Cortex-R8 feasibility")
    print("=" * 120)

    num_requests = 1000
    base_slice = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=67800,
        critical_fraction=0.4,
        deadline_slack_us=800.0
    )
    base_slice_bg = WorkloadGenerator.inject_background_traffic(base_slice, background_rate_iops=200.0, jitter=False)

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    queue_depths = [8, 16, 32]
    overhead_summary = []

    print(f"{'QD':<5} | {'Avg Candidates':<15} | {'SRAM Reads':<12} | {'Urgency Math':<14} | {'Delay Predict':<15} | {'Total Python':<14} | {'ARM Cycles':<12} | {'ARM Time':<12} | {'% of NAND Service'}")
    print("-" * 120)

    for qd in queue_depths:
        sched = GranularProfiledTEMPO()
        sim = Simulator(config=cfg, max_in_flight=qd)
        sim.run(copy.deepcopy(base_slice_bg), sched)

        cands = float(np.mean(sched.candidates_per_dispatch))
        sram = float(np.mean(sched.sram_lookups_per_dispatch))
        t_urg = float(np.mean(sched.urgency_calc_ns)) / 1000.0 # us
        t_pred = float(np.mean(sched.state_predict_ns)) / 1000.0 # us
        t_tot = float(np.mean(sched.total_decision_ns)) / 1000.0 # us

        # Controller estimation on compiled ARM Cortex-R8 @ 800 MHz (1.25 ns/cycle):
        # 1 candidate evaluation = ~15 instructions (urgency math) + 4 sub-pages * 10 instructions (SRAM deref & max) = ~55 instructions.
        # Plus dispatch commit = ~35 cycles.
        arm_cycles = int(35 + cands * 55)
        arm_time_us = (arm_cycles * 1.25) / 1000.0
        nand_read_us = 76.96 # 36 us sense + 40.96 us bus transfer
        overhead_pct = (arm_time_us / nand_read_us) * 100.0

        row = {
            "queue_depth": qd,
            "avg_candidates": round(cands, 1),
            "avg_sram_reads": round(sram, 1),
            "python_urgency_math_us": round(t_urg, 3),
            "python_delay_predict_us": round(t_pred, 3),
            "python_total_decision_us": round(t_tot, 3),
            "arm_cortex_r8_cycles": arm_cycles,
            "arm_cortex_r8_us": round(arm_time_us, 3),
            "overhead_pct_of_nand_read": round(overhead_pct, 2)
        }
        overhead_summary.append(row)

        print(f"{qd:<5} | {cands:<15.1f} | {sram:<12.1f} | {t_urg:<14.3f} | {t_pred:<15.3f} | {t_tot:<14.3f} | {arm_cycles:<12} | {arm_time_us:<12.3f} | {overhead_pct:<5.2f}%")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "overhead_granular.json")
    with open(out_file, "w") as f:
        json.dump(overhead_summary, f, indent=2)
    print(f"\nGranular overhead data saved to {out_file}")

if __name__ == "__main__":
    run_overhead_profiling()
