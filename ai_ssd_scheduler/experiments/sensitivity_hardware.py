"""Phase 8: Hardware Sensitivity Analysis.

Sweeps core NAND physical assumptions:
1. NAND Page Read Latency (tR): 25 us, 36 us, 50 us, 75 us
2. NAND Page Program Latency (tPROG): 100 us, 185 us, 300 us, 500 us
3. GC Block Erase Latency (tBERS): 1.0 ms, 2.0 ms, 3.5 ms, 5.0 ms
"""

import copy
import json
import os
import time
from typing import List, Dict, Any
from ..ssd.nand import SSDConfig
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

class HardwareSensitivityRunner:
    def __init__(self, num_requests: int = 1500, skip_initial: int = 67800, deadline_slack_us: float = 800.0, bg_iops: float = 200.0):
        self.num_requests = num_requests
        self.deadline_slack_us = deadline_slack_us
        self.bg_iops = bg_iops
        print(f"Pre-loading base slice of {num_requests} requests from CHEOPS KV-cache trace...")
        self.base_reqs = WorkloadGenerator.get_kv_offload_slice(
            num_requests=num_requests,
            skip_initial=skip_initial,
            critical_fraction=0.4,
            deadline_slack_us=deadline_slack_us
        )
        if bg_iops > 0:
            self.base_reqs = WorkloadGenerator.inject_background_traffic(self.base_reqs, background_rate_iops=bg_iops)
        print("Base slice loaded.\n")

    def sweep_read_latency(self, t_reads: List[float] = [25.0, 36.0, 50.0, 75.0]) -> List[Dict[str, Any]]:
        """Sweeps t_read (25 us = XL-FLASH/SLC, 36 us = 970 Pro baseline, 50 us = TLC, 75 us = QLC)."""
        print("=" * 115)
        print("SWEEP 1: NAND READ SENSING LATENCY (tR: 25 us -> 75 us)")
        print(f"Fixed: tPROG = 185 us, Slack = {self.deadline_slack_us} us, BG = {self.bg_iops} IOPS, QD = 32")
        print("=" * 115)
        print(f"{'tR (us)':<10} | {'Hardware Class':<18} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'P95 Win':<10}")
        print("-" * 115)

        hw_labels = {25.0: "Ultra-Fast SLC", 36.0: "970 Pro V-NAND", 50.0: "Standard TLC", 75.0: "High-Density QLC"}
        results = []

        for tr in t_reads:
            cfg = SSDConfig(t_read_us=tr, t_prog_us=185.0)
            
            sim_s1 = Simulator(config=cfg, max_in_flight=32)
            res_s1 = sim_s1.run(copy.deepcopy(self.base_reqs), AIPriorityScheduler())
            
            sim_s3 = Simulator(config=cfg, max_in_flight=32)
            res_s3 = sim_s3.run(copy.deepcopy(self.base_reqs), AIAndSSDStateScheduler())

            delta_miss = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
            p95_win = f"{(res_s1.critical_p95_us - res_s3.critical_p95_us):.1f} us"

            row = {
                "param": "t_read",
                "val": tr,
                "label": hw_labels.get(tr, "Custom"),
                "s1_miss": res_s1.critical_deadline_miss_pct,
                "s3_miss": res_s3.critical_deadline_miss_pct,
                "delta_miss": delta_miss,
                "s1_p95": res_s1.critical_p95_us,
                "s3_p95": res_s3.critical_p95_us,
                "s1_p99_9": res_s1.critical_p99_9_us,
                "s3_p99_9": res_s3.critical_p99_9_us
            }
            results.append(row)
            print(f"{tr:<10.1f} | {hw_labels.get(tr, ''):<18} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta_miss:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {p95_win:<10}")

        return results

    def sweep_prog_latency(self, t_progs: List[float] = [100.0, 185.0, 300.0, 500.0]) -> List[Dict[str, Any]]:
        """Sweeps t_prog (100 us = SLC buffer, 185 us = 970 Pro, 300 us = Fast TLC, 500 us = Deep TLC/QLC)."""
        print("\n" + "=" * 115)
        print("SWEEP 2: NAND PROGRAM/WRITE LATENCY (tPROG: 100 us -> 500 us)")
        print(f"Fixed: tR = 36 us, Slack = {self.deadline_slack_us} us, BG = {self.bg_iops} IOPS, QD = 32")
        print("=" * 115)
        print(f"{'tPROG (us)':<10} | {'Hardware Class':<18} | {'S1 Miss %':<12} | {'S3 Miss %':<12} | {'Miss Delta':<12} | {'S1 P95 (us)':<13} | {'S3 P95 (us)':<13} | {'P95 Win':<10}")
        print("-" * 115)

        hw_labels = {100.0: "SLC Buffer Cache", 185.0: "970 Pro V-NAND", 300.0: "Standard TLC", 500.0: "Deep TLC/QLC"}
        results = []

        for tp in t_progs:
            cfg = SSDConfig(t_read_us=36.0, t_prog_us=tp)
            
            sim_s1 = Simulator(config=cfg, max_in_flight=32)
            res_s1 = sim_s1.run(copy.deepcopy(self.base_reqs), AIPriorityScheduler())
            
            sim_s3 = Simulator(config=cfg, max_in_flight=32)
            res_s3 = sim_s3.run(copy.deepcopy(self.base_reqs), AIAndSSDStateScheduler())

            delta_miss = res_s1.critical_deadline_miss_pct - res_s3.critical_deadline_miss_pct
            p95_win = f"{(res_s1.critical_p95_us - res_s3.critical_p95_us):.1f} us"

            row = {
                "param": "t_prog",
                "val": tp,
                "label": hw_labels.get(tp, "Custom"),
                "s1_miss": res_s1.critical_deadline_miss_pct,
                "s3_miss": res_s3.critical_deadline_miss_pct,
                "delta_miss": delta_miss,
                "s1_p95": res_s1.critical_p95_us,
                "s3_p95": res_s3.critical_p95_us,
                "s1_p99_9": res_s1.critical_p99_9_us,
                "s3_p99_9": res_s3.critical_p99_9_us
            }
            results.append(row)
            print(f"{tp:<10.1f} | {hw_labels.get(tp, ''):<18} | {res_s1.critical_deadline_miss_pct:<12.1f} | {res_s3.critical_deadline_miss_pct:<12.1f} | {delta_miss:<12.1f} | {res_s1.critical_p95_us:<13.1f} | {res_s3.critical_p95_us:<13.1f} | {p95_win:<10}")

        return results

    def sweep_gc_latency(self, t_erases: List[float] = [1.0, 2.0, 3.5, 5.0]) -> List[Dict[str, Any]]:
        """Sweeps t_erase with GC events (1.0 ms = SLC, 2.0 ms = eMLC, 3.5 ms = 3D TLC, 5.0 ms = Degraded QLC)."""
        print("\n" + "=" * 115)
        print("SWEEP 3: GC BLOCK ERASE LATENCY (tBERS: 1.0 ms -> 5.0 ms)")
        print(f"Fixed: tR = 36 us, tPROG = 185 us, Slack = 1200 us, QD = 32")
        print("=" * 115)
        print(f"{'tBERS (ms)':<10} | {'Hardware Class':<18} | {'S1 P99 (us)':<13} | {'S3 P99 (us)':<13} | {'P99 Win':<12} | {'S1 P99.9 (us)':<14} | {'S3 P99.9 (us)':<14} | {'P99.9 Win':<12}")
        print("-" * 115)

        hw_labels = {1.0: "SLC Block Erase", 2.0: "eMLC Multi-Plane", 3.5: "3D TLC Baseline", 5.0: "Degraded QLC"}
        results = []

        # Prepare GC events (8 events evenly spaced)
        t_start = self.base_reqs[0].arrival_time_us
        t_end = self.base_reqs[-1].arrival_time_us
        duration_us = t_end - t_start
        num_gcs = 8
        interval = duration_us / (num_gcs + 1)

        for te in t_erases:
            cfg = SSDConfig(t_read_us=36.0, t_prog_us=185.0)
            
            gc_events = []
            for g in range(num_gcs):
                t_gc = t_start + (g + 1) * interval
                ch = g % 8
                lun = (g // 8) % 2
                gc_events.append((t_gc, ch, lun, te * 1000.0))

            sim_s1 = Simulator(config=cfg, max_in_flight=32)
            res_s1 = sim_s1.run(copy.deepcopy(self.base_reqs), AIPriorityScheduler(), gc_events=gc_events)

            sim_s3 = Simulator(config=cfg, max_in_flight=32)
            res_s3 = sim_s3.run(copy.deepcopy(self.base_reqs), AIAndSSDStateScheduler(), gc_events=gc_events)

            p99_win = f"{(res_s1.critical_p99_us - res_s3.critical_p99_us):.1f} us"
            p999_win = f"{(res_s1.critical_p99_9_us - res_s3.critical_p99_9_us):.1f} us"

            row = {
                "param": "t_erase",
                "val": te,
                "label": hw_labels.get(te, "Custom"),
                "s1_p99": res_s1.critical_p99_us,
                "s3_p99": res_s3.critical_p99_us,
                "s1_p99_9": res_s1.critical_p99_9_us,
                "s3_p99_9": res_s3.critical_p99_9_us,
                "s1_miss": res_s1.critical_deadline_miss_pct,
                "s3_miss": res_s3.critical_deadline_miss_pct
            }
            results.append(row)
            print(f"{te:<10.1f} | {hw_labels.get(te, ''):<18} | {res_s1.critical_p99_us:<13.1f} | {res_s3.critical_p99_us:<13.1f} | {p99_win:<12} | {res_s1.critical_p99_9_us:<14.1f} | {res_s3.critical_p99_9_us:<14.1f} | {p999_win:<12}")

        return results

def run_all_sensitivity():
    runner = HardwareSensitivityRunner(num_requests=1500, deadline_slack_us=800.0, bg_iops=200.0)
    all_res = {
        "read_sensitivity": runner.sweep_read_latency(),
        "prog_sensitivity": runner.sweep_prog_latency(),
        "gc_sensitivity": runner.sweep_gc_latency()
    }
    
    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "hardware_sensitivity.json")
    with open(out_file, "w") as f:
        json.dump(all_res, f, indent=2)
    print(f"\nHardware sensitivity analysis saved to {out_file}")

if __name__ == "__main__":
    run_all_sensitivity()
