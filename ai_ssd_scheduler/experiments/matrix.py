"""Phase 4: Systematic Experimental Matrix across 4 Key Dimensions.

Dimensions:
- Dimension A: AI Deadline Slack (400, 600, 800, 1000, 1200, 1500, 2000, 3000 us)
- Dimension B: Background Write Contention (0, 50, 100, 200, 400, 800, 1600 IOPS)
- Dimension C: GC Interference Duration (0, 1.0, 2.0, 3.5, 5.0 ms)
- Dimension D: Controller Queue Depth (1, 2, 4, 8, 16, 32, 64)
"""

import copy
import json
import os
import time
from typing import List, Dict, Any
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator, SimulationResult
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def get_schedulers():
    return [
        ("S0-FIFO", lambda: FIFOScheduler()),
        ("S1-AI-Priority", lambda: AIPriorityScheduler()),
        ("S2-SSD-State", lambda: SSDStateScheduler()),
        ("S3-AI+SSD-State", lambda: AIAndSSDStateScheduler())
    ]

class MatrixRunner:
    def __init__(self, num_requests: int = 1500, skip_initial: int = 67800):
        self.num_requests = num_requests
        self.skip_initial = skip_initial
        print(f"Pre-loading base slice of {num_requests} requests from CHEOPS KV-cache trace...")
        self.raw_slice = WorkloadGenerator.get_kv_offload_slice(
            num_requests=num_requests,
            skip_initial=skip_initial,
            critical_fraction=0.4,
            deadline_slack_us=1200.0
        )
        print("Base slice loaded.\n")

    def run_dimension_a_deadlines(
        self,
        deadlines_us: List[float] = [400.0, 600.0, 800.0, 1000.0, 1200.0, 1500.0, 2000.0, 3000.0],
        fixed_bg_iops: float = 200.0,
        fixed_qd: int = 32
    ) -> List[Dict[str, Any]]:
        """Complete curve across deadline slacks."""
        print("=" * 100)
        print("DIMENSION A: AI DEADLINE SLACK CURVE")
        print(f"Slacks: {deadlines_us} us | Fixed BG: {fixed_bg_iops} IOPS | Fixed QD: {fixed_qd}")
        print("=" * 100)
        print(f"{'Slack (us)':<12} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<14}")
        print("-" * 96)

        results = []
        for slack in deadlines_us:
            # Re-annotate slice with current deadline slack
            base_reqs = copy.deepcopy(self.raw_slice)
            for r in base_reqs:
                if r.priority.name == "CRITICAL":
                    r.deadline_us = r.arrival_time_us + slack
            if fixed_bg_iops > 0:
                base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=fixed_bg_iops)

            for s_name, s_factory in get_schedulers():
                sched = s_factory()
                sim = Simulator(config=SSDConfig(), max_in_flight=fixed_qd)
                res = sim.run(copy.deepcopy(base_reqs), sched)
                
                row = {
                    "dimension": "A_deadline",
                    "param_val": slack,
                    "scheduler": s_name,
                    "crit_p50": res.critical_p50_us,
                    "crit_p95": res.critical_p95_us,
                    "crit_p99": res.critical_p99_us,
                    "miss_pct": res.critical_deadline_miss_pct,
                    "miss_count": res.critical_deadline_misses,
                    "throughput": res.throughput_mb_s
                }
                results.append(row)
                miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
                print(f"{slack:<12.0f} | {s_name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<14}")
            print("-" * 96)
        return results

    def run_dimension_b_background(
        self,
        bg_levels: List[float] = [0.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0],
        fixed_slack_us: float = 1000.0,
        fixed_qd: int = 32
    ) -> List[Dict[str, Any]]:
        """Complete curve across background write contention."""
        print("\n" + "=" * 100)
        print("DIMENSION B: BACKGROUND WRITE CONTENTION CURVE")
        print(f"BG IOPS: {bg_levels} | Fixed Slack: {fixed_slack_us} us | Fixed QD: {fixed_qd}")
        print("=" * 100)
        print(f"{'BG IOPS':<12} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<14}")
        print("-" * 96)

        results = []
        for bg in bg_levels:
            base_reqs = copy.deepcopy(self.raw_slice)
            for r in base_reqs:
                if r.priority.name == "CRITICAL":
                    r.deadline_us = r.arrival_time_us + fixed_slack_us
            if bg > 0:
                base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=bg)

            for s_name, s_factory in get_schedulers():
                sched = s_factory()
                sim = Simulator(config=SSDConfig(), max_in_flight=fixed_qd)
                res = sim.run(copy.deepcopy(base_reqs), sched)
                
                row = {
                    "dimension": "B_background",
                    "param_val": bg,
                    "scheduler": s_name,
                    "crit_p50": res.critical_p50_us,
                    "crit_p95": res.critical_p95_us,
                    "crit_p99": res.critical_p99_us,
                    "miss_pct": res.critical_deadline_miss_pct,
                    "miss_count": res.critical_deadline_misses,
                    "throughput": res.throughput_mb_s
                }
                results.append(row)
                miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
                print(f"{bg:<12.0f} | {s_name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<14}")
            print("-" * 96)
        return results

    def run_dimension_c_gc(
        self,
        erase_latencies_ms: List[float] = [0.0, 1.0, 2.0, 3.5, 5.0],
        fixed_slack_us: float = 1200.0,
        fixed_qd: int = 32
    ) -> List[Dict[str, Any]]:
        """
        Complete curve across GC block erase latencies:
        - 0.0 ms: GC OFF (Pure workload)
        - 1.0 ms: GC LOW (SLC single-plane block erase, ~1ms)
        - 2.0 ms: GC MEDIUM (Typical multi-plane SLC/MLC erase, ~2ms)
        - 3.5 ms: GC HIGH (Standard 3D TLC/QLC erase baseline, ~3.5ms)
        - 5.0 ms: GC STRESS (Heavily cycled / degraded QLC erase, ~5ms)
        """
        print("\n" + "=" * 100)
        print("DIMENSION C: GC INTERFERENCE DURATION CURVE")
        print(f"Erase Latencies: {erase_latencies_ms} ms | Fixed Slack: {fixed_slack_us} us | Fixed QD: {fixed_qd}")
        print("=" * 100)
        print(f"{'Erase (ms)':<12} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<14}")
        print("-" * 96)

        results = []
        for erase_ms in erase_latencies_ms:
            base_reqs = copy.deepcopy(self.raw_slice)
            for r in base_reqs:
                if r.priority.name == "CRITICAL":
                    r.deadline_us = r.arrival_time_us + fixed_slack_us

            gc_events = []
            if erase_ms > 0:
                t_start = base_reqs[0].arrival_time_us
                t_end = base_reqs[-1].arrival_time_us
                duration_us = t_end - t_start
                num_gcs = 8
                interval = duration_us / (num_gcs + 1)
                for g in range(num_gcs):
                    t_gc = t_start + (g + 1) * interval
                    ch = g % 8
                    lun = (g // 8) % 2
                    gc_events.append((t_gc, ch, lun, erase_ms * 1000.0))

            for s_name, s_factory in get_schedulers():
                sched = s_factory()
                sim = Simulator(config=SSDConfig(), max_in_flight=fixed_qd)
                res = sim.run(copy.deepcopy(base_reqs), sched, gc_events=gc_events)
                
                row = {
                    "dimension": "C_gc",
                    "param_val": erase_ms,
                    "scheduler": s_name,
                    "crit_p50": res.critical_p50_us,
                    "crit_p95": res.critical_p95_us,
                    "crit_p99": res.critical_p99_us,
                    "miss_pct": res.critical_deadline_miss_pct,
                    "miss_count": res.critical_deadline_misses,
                    "throughput": res.throughput_mb_s
                }
                results.append(row)
                miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
                print(f"{erase_ms:<12.1f} | {s_name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<14}")
            print("-" * 96)
        return results

    def run_dimension_d_queue_depth(
        self,
        queue_depths: List[int] = [1, 2, 4, 8, 16, 32, 64],
        fixed_slack_us: float = 1000.0,
        fixed_bg_iops: float = 200.0
    ) -> List[Dict[str, Any]]:
        """
        Tests Queue Depth scaling.
        Hypothesis: At QD=1, no scheduling choices exist (all schedulers identical).
        As QD increases, scheduling degrees of freedom expand, maximizing state awareness.
        """
        print("\n" + "=" * 100)
        print("DIMENSION D: CONTROLLER QUEUE DEPTH SCALING")
        print(f"Queue Depths: {queue_depths} | Fixed Slack: {fixed_slack_us} us | Fixed BG: {fixed_bg_iops} IOPS")
        print("=" * 100)
        print(f"{'QD':<12} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<14}")
        print("-" * 96)

        results = []
        for qd in queue_depths:
            base_reqs = copy.deepcopy(self.raw_slice)
            for r in base_reqs:
                if r.priority.name == "CRITICAL":
                    r.deadline_us = r.arrival_time_us + fixed_slack_us
            if fixed_bg_iops > 0:
                base_reqs = WorkloadGenerator.inject_background_traffic(base_reqs, background_rate_iops=fixed_bg_iops)

            for s_name, s_factory in get_schedulers():
                sched = s_factory()
                sim = Simulator(config=SSDConfig(), max_in_flight=qd)
                res = sim.run(copy.deepcopy(base_reqs), sched)
                
                row = {
                    "dimension": "D_queue_depth",
                    "param_val": qd,
                    "scheduler": s_name,
                    "crit_p50": res.critical_p50_us,
                    "crit_p95": res.critical_p95_us,
                    "crit_p99": res.critical_p99_us,
                    "miss_pct": res.critical_deadline_miss_pct,
                    "miss_count": res.critical_deadline_misses,
                    "throughput": res.throughput_mb_s
                }
                results.append(row)
                miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
                print(f"{qd:<12d} | {s_name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<14}")
            print("-" * 96)
        return results

def run_all_dimensions():
    runner = MatrixRunner(num_requests=1500)
    all_results = {}
    
    t0 = time.time()
    all_results["dimension_a"] = runner.run_dimension_a_deadlines()
    all_results["dimension_b"] = runner.run_dimension_b_background()
    all_results["dimension_c"] = runner.run_dimension_c_gc()
    all_results["dimension_d"] = runner.run_dimension_d_queue_depth()
    
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", "matrix_results.json")
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
        
    print(f"\nCompleted complete 4-dimension experimental matrix in {time.time() - t0:.2f}s.")
    print(f"Results saved to {out_path}")

if __name__ == "__main__":
    run_all_dimensions()
