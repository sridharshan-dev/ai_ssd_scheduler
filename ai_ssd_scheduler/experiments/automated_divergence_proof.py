"""Phase 4: Automated Mechanism Proof (10-20 Concrete Decision Timelines).

Extracts 15 concrete scheduling divergences using the verified decision tracer:
- S1 picks Request A (because A arrived earlier), but A targets a busy channel.
- S3 picks Request B (because B targets an idle channel).
- B completes earlier under S3, avoiding channel head-of-line stalls.
"""

import json
import os
from .decision_tracer import find_scheduling_divergences

def run_automated_divergence_proof():
    print("=" * 120)
    print("PHASE 4: AUTOMATED MECHANISM PROOF (EXTRACTING DIVERGENCE TIMELINES)")
    print("Extracting 15 concrete scheduling divergences from CHEOPS trace execution")
    print("=" * 120)

    # Extract 15 divergences
    divergences = find_scheduling_divergences(
        num_requests=3000,
        skip_initial=67800,
        critical_fraction=0.4,
        deadline_slack_us=800.0,
        bg_iops=200.0,
        max_divergences=15
    )

    print(f"\nSuccessfully identified {len(divergences)} distinct divergence instances where S1 and S3 made different decisions.")
    
    div_records = []
    for idx, d in enumerate(divergences, 1):
        c_s1 = next(c for c in d.candidates if c.req_id == d.s1_selected_id)
        c_s3 = next(c for c in d.candidates if c.req_id == d.s3_selected_id)

        entry = {
            "case_number": idx,
            "simulation_time_us": round(d.timestamp_us, 1),
            "queue_depth": d.queue_depth,
            "s1_choice_req_A": {
                "id": c_s1.req_id,
                "priority": c_s1.priority,
                "arrival_us": round(c_s1.arrival_time_us, 1),
                "deadline_us": round(c_s1.deadline_us, 1),
                "slack_us": round(c_s1.slack_us, 1),
                "target_channels": c_s1.mapped_channels,
                "target_luns": c_s1.mapped_luns,
                "hardware_ready": c_s1.is_channel_idle,
                "blocking_reason": c_s1.blocking_reason,
                "predicted_delay_us": round(c_s1.predicted_delay_us, 1)
            },
            "s3_choice_req_B": {
                "id": c_s3.req_id,
                "priority": c_s3.priority,
                "arrival_us": round(c_s3.arrival_time_us, 1),
                "deadline_us": round(c_s3.deadline_us, 1),
                "slack_us": round(c_s3.slack_us, 1),
                "target_channels": c_s3.mapped_channels,
                "target_luns": c_s3.mapped_luns,
                "hardware_ready": c_s3.is_channel_idle,
                "blocking_reason": c_s3.blocking_reason,
                "predicted_delay_us": round(c_s3.predicted_delay_us, 1)
            },
            "s1_outcome": d.s1_outcome,
            "s3_outcome": d.s3_outcome
        }
        div_records.append(entry)

        if idx <= 5:
            print(f"\n[Case #{idx} at t={d.timestamp_us:.1f} us]")
            print(f"  Req A (ID {c_s1.req_id}): Arr {c_s1.arrival_time_us:.1f} us, Channels {c_s1.mapped_channels}, Delay {c_s1.predicted_delay_us:.1f} us ({c_s1.blocking_reason})")
            print(f"  Req B (ID {c_s3.req_id}): Arr {c_s3.arrival_time_us:.1f} us, Channels {c_s3.mapped_channels}, Delay {c_s3.predicted_delay_us:.1f} us ({c_s3.blocking_reason})")
            print(f"  --> S1 Dispatches: Req A (FIFO tie-break on arrival order)")
            print(f"  --> S3 Dispatches: Req B (B avoids channel conflict and executes {c_s1.predicted_delay_us - c_s3.predicted_delay_us:.1f} us sooner)")

    os.makedirs("results", exist_ok=True)
    out_file = os.path.join("results", "automated_divergences.json")
    with open(out_file, "w") as f:
        json.dump(div_records, f, indent=2)
    print(f"\nSaved {len(div_records)} divergence records to {out_file}")

if __name__ == "__main__":
    run_automated_divergence_proof()
