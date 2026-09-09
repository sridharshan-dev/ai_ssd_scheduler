"""Command-line entry point for running AI-SSD scheduler experiments."""

import argparse
import sys
import os

# Ensure package root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ai_ssd_scheduler.experiments.baseline import run_baseline_experiment

def main():
    parser = argparse.ArgumentParser(description="AI-Aware SSD Discrete-Event Simulator (CHEOPS'25 Trace Driven)")
    parser.add_argument("--num-requests", type=int, default=5000, help="Number of trace requests to simulate")
    parser.add_argument("--skip-initial", type=int, default=67800, help="Line offset to skip warmup writes")
    parser.add_argument("--critical-fraction", type=float, default=0.4, help="Fraction of reads marked as Critical AI KV reads")
    parser.add_argument("--deadline-slack", type=float, default=1200.0, help="Deadline slack in microseconds for Critical requests")
    parser.add_argument("--bg-iops", type=float, default=200.0, help="Injected background write IOPS (contention)")
    parser.add_argument("--queue-depth", type=int, default=32, help="Max in-flight requests on the SSD")
    
    args = parser.parse_args()

    run_baseline_experiment(
        num_requests=args.num_requests,
        skip_initial=args.skip_initial,
        critical_fraction=args.critical_fraction,
        deadline_slack_us=args.deadline_slack,
        inject_background_iops=args.bg_iops,
        max_queue_depth=args.queue_depth
    )

if __name__ == "__main__":
    main()
