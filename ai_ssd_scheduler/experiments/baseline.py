"""Baseline experiment runner comparing the four schedulers."""

import copy
import time
from typing import List, Dict
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator, SimulationResult
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def run_baseline_experiment(
    num_requests: int = 5000,
    skip_initial: int = 67800,
    critical_fraction: float = 0.4,
    deadline_slack_us: float = 1200.0,
    inject_background_iops: float = 0.0,
    max_queue_depth: int = 32
) -> List[SimulationResult]:
    """
    Executes the 4 schedulers on identical CHEOPS trace requests and compares metrics.
    """
    print(f"\n=======================================================")
    print(f"Loading {num_requests} requests from CHEOPS KV-cache trace...")
    print(f"  Trace Offset: line {skip_initial} (active decode phase)")
    print(f"  AI Critical Ratio: {critical_fraction*100:.1f}%")
    print(f"  Critical Deadline Slack: {deadline_slack_us:.1f} us")
    if inject_background_iops > 0:
        print(f"  Injected Background Traffic: {inject_background_iops} IOPS")
    print(f"=======================================================\n")

    base_requests = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=critical_fraction,
        deadline_slack_us=deadline_slack_us
    )

    if inject_background_iops > 0:
        base_requests = WorkloadGenerator.inject_background_traffic(
            base_requests,
            background_rate_iops=inject_background_iops
        )

    schedulers = [
        FIFOScheduler(),
        AIPriorityScheduler(),
        SSDStateScheduler(),
        AIAndSSDStateScheduler()
    ]

    results: List[SimulationResult] = []
    config = SSDConfig()

    for sched in schedulers:
        # Create a clean copy of the request list with reset timestamps
        req_copy = copy.deepcopy(base_requests)
        sim = Simulator(config=config, max_in_flight=max_queue_depth)
        
        t0 = time.time()
        res = sim.run(req_copy, sched)
        wall_s = time.time() - t0
        
        print(f"Completed {sched.name} in {wall_s:.2f}s real time.")
        results.append(res)

    print_comparison_table(results)
    return results

def print_comparison_table(results: List[SimulationResult]):
    """Prints a comparative markdown table across the schedulers."""
    print("\n" + "=" * 90)
    print(f"{'Scheduler':<20} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<12} | {'Throughput (MB/s)':<18}")
    print("-" * 90)
    
    for r in results:
        miss_str = f"{r.critical_deadline_misses} ({r.critical_deadline_miss_pct:.1f}%)"
        print(f"{r.scheduler_name:<20} | {r.critical_p50_us:<14.1f} | {r.critical_p95_us:<14.1f} | {r.critical_p99_us:<14.1f} | {miss_str:<12} | {r.throughput_mb_s:<18.1f}")
    print("=" * 90 + "\n")
