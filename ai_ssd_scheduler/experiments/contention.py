"""Contention and sensitivity parameter sweep runner."""

import copy
from typing import List, Dict, Tuple
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.fifo import FIFOScheduler
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ssd_state import SSDStateScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

def sweep_contention(
    num_requests: int = 2000,
    background_levels: List[float] = [0.0, 100.0, 300.0, 600.0, 1000.0]
):
    """Varies background I/O contention to measure impact across all 4 schedulers."""
    print("\n" + "=" * 90)
    print(f"SWEEP 1: Background Write Contention Levels (IOPS: {background_levels})")
    print(f"Requests per run: {num_requests} from real CHEOPS KV-cache trace")
    print("=" * 90)

    schedulers_factory = [
        ("S0-FIFO", lambda: FIFOScheduler()),
        ("S1-AI-Priority", lambda: AIPriorityScheduler()),
        ("S2-SSD-State", lambda: SSDStateScheduler()),
        ("S3-AI+SSD-State", lambda: AIAndSSDStateScheduler())
    ]

    print(f"\n{'BG IOPS':<10} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<12}")
    print("-" * 88)

    for bg in background_levels:
        base_requests = WorkloadGenerator.get_kv_offload_slice(
            num_requests=num_requests,
            skip_initial=67800,
            critical_fraction=0.4,
            deadline_slack_us=1200.0
        )
        if bg > 0:
            base_requests = WorkloadGenerator.inject_background_traffic(base_requests, background_rate_iops=bg)

        for name, factory in schedulers_factory:
            sched = factory()
            req_copy = copy.deepcopy(base_requests)
            sim = Simulator(config=SSDConfig(), max_in_flight=32)
            res = sim.run(req_copy, sched)
            
            miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
            print(f"{bg:<10.0f} | {name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<12}")
        print("-" * 88)

def sweep_deadlines(
    num_requests: int = 2000,
    deadlines_us: List[float] = [600.0, 1000.0, 1500.0, 2500.0]
):
    """Varies deadline slack from tight to loose under moderate contention."""
    print("\n" + "=" * 90)
    print(f"SWEEP 2: AI Deadline Slack (Slack: {deadlines_us} us)")
    print("=" * 90)

    schedulers_factory = [
        ("S0-FIFO", lambda: FIFOScheduler()),
        ("S1-AI-Priority", lambda: AIPriorityScheduler()),
        ("S2-SSD-State", lambda: SSDStateScheduler()),
        ("S3-AI+SSD-State", lambda: AIAndSSDStateScheduler())
    ]

    print(f"\n{'Slack (us)':<10} | {'Scheduler':<18} | {'Crit P50 (us)':<14} | {'Crit P95 (us)':<14} | {'Crit P99 (us)':<14} | {'Misses (%)':<12}")
    print("-" * 88)

    for slack in deadlines_us:
        base_requests = WorkloadGenerator.get_kv_offload_slice(
            num_requests=num_requests,
            skip_initial=67800,
            critical_fraction=0.4,
            deadline_slack_us=slack
        )
        base_requests = WorkloadGenerator.inject_background_traffic(base_requests, background_rate_iops=200.0)

        for name, factory in schedulers_factory:
            sched = factory()
            req_copy = copy.deepcopy(base_requests)
            sim = Simulator(config=SSDConfig(), max_in_flight=32)
            res = sim.run(req_copy, sched)
            
            miss_str = f"{res.critical_deadline_misses} ({res.critical_deadline_miss_pct:.1f}%)"
            print(f"{slack:<10.0f} | {name:<18} | {res.critical_p50_us:<14.1f} | {res.critical_p95_us:<14.1f} | {res.critical_p99_us:<14.1f} | {miss_str:<12}")
        print("-" * 88)

if __name__ == "__main__":
    sweep_contention(num_requests=1500, background_levels=[0.0, 200.0, 500.0])
    sweep_deadlines(num_requests=1500, deadlines_us=[800.0, 1500.0])
