"""Experiment evaluating GC and Background Interference collision."""

import copy
from typing import List
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator, SimulationResult
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_gc_collision_experiment(
    num_requests: int = 2000,
    gc_pause_us: float = 3500.0,  # 3.5 ms block erase
    gc_frequency_requests: int = 200
) -> List[SimulationResult]:
    """
    Simulates periodic GC events on NAND channels to test how schedulers handle
    hardware interference and head-of-line blocking.
    """
    base_requests = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=67800,
        critical_fraction=0.4,
        deadline_slack_us=1500.0
    )

    # Generate synthetic GC events periodically across channels
    gc_events = []
    if base_requests:
        t_start = base_requests[0].arrival_time_us
        t_end = base_requests[-1].arrival_time_us
        duration_us = t_end - t_start
        
        # Inject periodic GC pauses (e.g. 3.5ms block erases) on alternating channels
        num_gcs = int(len(base_requests) / gc_frequency_requests)
        interval = duration_us / max(1, num_gcs)
        
        for g in range(num_gcs):
            t_gc = t_start + (g + 0.5) * interval
            ch = g % 8
            lun = (g // 8) % 2
            gc_events.append((t_gc, ch, lun, gc_pause_us))

    print(f"\n=======================================================")
    print(f"Running GC Collision Experiment:")
    print(f"  Requests: {num_requests} from CHEOPS KV-cache trace")
    print(f"  Injected GC Pauses: {len(gc_events)} events of {gc_pause_us/1000:.2f} ms each")
    print(f"=======================================================\n")

    schedulers = [
        FIFOScheduler(),
        AIPriorityScheduler(),
        SSDStateScheduler(),
        AIAndSSDStateScheduler()
    ]

    results: List[SimulationResult] = []
    config = SSDConfig()

    for sched in schedulers:
        req_copy = copy.deepcopy(base_requests)
        sim = Simulator(config=config, max_in_flight=32)
        res = sim.run(req_copy, sched, gc_events=gc_events)
        results.append(res)

    print("\n" + "=" * 90)
    print(f"{'Scheduler':<20} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<12} | {'Max Lat (us)':<14}")
    print("-" * 90)
    for r in results:
        miss_str = f"{r.critical_deadline_misses} ({r.critical_deadline_miss_pct:.1f}%)"
        print(f"{r.scheduler_name:<20} | {r.critical_p50_us:<14.1f} | {r.critical_p95_us:<14.1f} | {r.critical_p99_us:<14.1f} | {miss_str:<12} | {r.critical_max_us:<14.1f}")
    print("=" * 90 + "\n")

    return results

if __name__ == "__main__":
    run_gc_collision_experiment()
