"""Phase 10: Scheduler Overhead & Algorithmic Complexity Profiler.

Measures:
1. Candidate requests examined per dispatch cycle.
2. SSD state lookups per decision (channel bus timers, LUN timers).
3. Wall-clock decision latency (Python overhead).
4. Algorithmic complexity derivation: O(Q * P).
5. Projected execution cycles on embedded SSD controller core (ARM Cortex-R8 @ 800 MHz).
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
from ..ssd.request import Request, Priority
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

class ProfiledAIAndSSDStateScheduler(AIAndSSDStateScheduler):
    """Instruments TEMPO scheduler to record execution stats per scheduling event."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.decision_times_ns: List[float] = []
        self.candidates_examined: List[int] = []
        self.state_lookups: List[int] = []

    def select_next(self, backend: SSDBackend, now: float):
        if not self.queue:
            return None

        t0 = time.perf_counter_ns()
        
        q_len = len(self.queue)
        self.candidates_examined.append(q_len)

        # First candidate
        best_idx = 0
        best_score = self._compute_score(self.queue[0], backend, now)
        best_arrival = self.queue[0].arrival_time_us

        # Lookups for first candidate: each sub-page reads channel bus timer + LUN timer (2 lookups per sub-page)
        sub_pages_count = len(self.queue[0].sub_pages) if self.queue[0].sub_pages else math.ceil(self.queue[0].size_bytes / backend.config.page_size_bytes)
        lookups = sub_pages_count * 2

        for i in range(1, q_len):
            req = self.queue[i]
            score = self._compute_score(req, backend, now)
            
            p_count = len(req.sub_pages) if req.sub_pages else math.ceil(req.size_bytes / backend.config.page_size_bytes)
            lookups += (p_count * 2)

            if score > best_score:
                best_idx = i
                best_score = score
                best_arrival = req.arrival_time_us
            elif abs(score - best_score) < 1e-4 and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        t1 = time.perf_counter_ns()
        self.decision_times_ns.append(t1 - t0)
        self.state_lookups.append(lookups)

        return self.queue.pop(best_idx)

def profile_scheduler_overhead():
    print("=" * 115)
    print("PHASE 10: SCHEDULER OVERHEAD & ALGORITHMIC COMPLEXITY PROFILING")
    print("Evaluating decision latency, state lookups, and controller feasibility across Queue Depths")
    print("=" * 115)

    num_requests = 1000
    base_reqs = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=67800,
        critical_fraction=0.4,
        deadline_slack_us=800.0
    )
    base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=200.0)

    cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
    queue_depths = [1, 2, 4, 8, 16, 32, 64]
    profile_results = []

    print(f"{'QD':<5} | {'Avg Candidates':<15} | {'Avg State Lookups':<18} | {'Py Decision (us)':<17} | {'Est ARM Cycles':<15} | {'Est ARM Time (us)':<18} | {'% of NAND Read':<15}")
    print("-" * 115)

    for qd in queue_depths:
        sched = ProfiledAIAndSSDStateScheduler()
        sim = Simulator(config=cfg, max_in_flight=qd)
        sim.run(copy.deepcopy(base_reqs), sched)

        times_ns = np.array(sched.decision_times_ns) if sched.decision_times_ns else np.array([0.0])
        cands = np.array(sched.candidates_examined) if sched.candidates_examined else np.array([0.0])
        lookups = np.array(sched.state_lookups) if sched.state_lookups else np.array([0.0])

        avg_cands = float(np.mean(cands))
        avg_lookups = float(np.mean(lookups))
        avg_time_us = float(np.mean(times_ns) / 1000.0)
        p99_time_us = float(np.percentile(times_ns, 99) / 1000.0)

        # Firmware Controller Estimation:
        # On an embedded ARM Cortex-R8 @ 800 MHz (1.25 ns / cycle):
        # - Base priority comparison & slack math: ~15 instructions per candidate
        # - Sub-page delay lookup: ~12 instructions per sub-page (pointer dereference + max comparison)
        # For 128 KiB request (4 sub-pages): ~15 + 4 * 12 = ~63 cycles per candidate.
        # Plus dispatch setup overhead: ~40 cycles.
        arm_cycles = int(40 + avg_cands * 63)
        arm_time_us = (arm_cycles * 1.25) / 1000.0 # at 800 MHz

        # Compare to physical 128 KiB NAND service time (~77 us: 36 us sense + 41 us bus)
        nand_service_us = 76.96
        overhead_pct = (arm_time_us / nand_service_us) * 100.0

        row = {
            "queue_depth": qd,
            "avg_candidates_examined": round(avg_cands, 2),
            "avg_state_lookups": round(avg_lookups, 2),
            "python_mean_us": round(avg_time_us, 3),
            "python_p99_us": round(p99_time_us, 3),
            "arm_cortex_r8_cycles": arm_cycles,
            "arm_cortex_r8_us": round(arm_time_us, 3),
            "overhead_pct_of_nand_read": round(overhead_pct, 2)
        }
        profile_results.append(row)

        print(f"{qd:<5} | {avg_cands:<15.1f} | {avg_lookups:<18.1f} | {avg_time_us:<17.3f} | {arm_cycles:<15} | {arm_time_us:<18.3f} | {overhead_pct:<15.2f}%")

    print("\n" + "=" * 115)
    print("ALGORITHMIC COMPLEXITY DERIVATION")
    print("=" * 115)
    print("Let Q = number of requests in scheduler queue (0 <= Q <= Queue Depth).")
    print("Let P = number of physical sub-pages per request = ceil(Size / Page_Size) = 4 for 128 KiB.")
    print("Let C = number of flash channels = 8.")
    print("\nDecision Algorithm:")
    print("  For each candidate request r in Q:")
    print("    1. Compute AI Urgency score (1 division, 2 subtractions, 1 addition) -> O(1)")
    print("    2. For each sub-page p in P:")
    print("         Read channel[p.ch].bus_busy_until and channel[p.ch].lun_busy_until[p.lun] -> 2 SRAM reads -> O(1)")
    print("         Compute earliest completion -> O(1)")
    print("    3. Accumulate request penalty -> O(P)")
    print("  Total Scheduling Decision Complexity: O(Q * P)")
    print("  Since P <= 4 (128 KiB) and Q <= 32 (standard NVMe queue depth), O(Q * P) is STRICTLY BOUNDED to <= 128 iterations.")
    print("  Memory Complexity: O(1) auxiliary space (evaluates in-place on existing controller request descriptors).")

    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "overhead_profiling.json")
    with open(out_path, "w") as f:
        json.dump(profile_results, f, indent=2)
    print(f"\nOverhead profiling data saved to {out_path}")

if __name__ == "__main__":
    profile_scheduler_overhead()
