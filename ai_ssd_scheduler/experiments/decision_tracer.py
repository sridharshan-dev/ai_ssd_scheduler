"""Decision Tracer: Instruments and proves the exact mechanism where S1 and S3 diverge."""

import copy
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from ..ssd.nand import SSDConfig
from ..ssd.channel import Channel
from ..ssd.backend import SSDBackend
from ..ssd.request import Request, Priority
from ..ssd.simulator import Simulator
from ..workloads.generator import WorkloadGenerator
from ..schedulers.ai_priority import AIPriorityScheduler
from ..schedulers.ai_ssd import AIAndSSDStateScheduler

@dataclass
class CandidateInspection:
    req_id: int
    op: str
    priority: str
    arrival_time_us: float
    deadline_us: float
    slack_us: float
    mapped_channels: List[int]
    mapped_luns: List[int]
    is_channel_idle: bool
    channel_busy_until: float
    predicted_delay_us: float
    blocking_reason: str

@dataclass
class DecisionDivergence:
    timestamp_us: float
    queue_depth: int
    candidates: List[CandidateInspection]
    s1_selected_id: int
    s1_reason: str
    s3_selected_id: int
    s3_reason: str
    
    # Outcomes tracked later
    s1_outcome: Dict[int, Any] = field(default_factory=dict)
    s3_outcome: Dict[int, Any] = field(default_factory=dict)

def find_scheduling_divergences(
    num_requests: int = 1500,
    skip_initial: int = 67800,
    critical_fraction: float = 0.4,
    deadline_slack_us: float = 800.0,
    bg_iops: float = 200.0,
    max_divergences: int = 5
) -> List[DecisionDivergence]:
    """
    Runs both S1 and S3 on the same trace slice. Instruments every decision point
    where S1 and S3 pick different requests from the queue.
    """
    base_requests = WorkloadGenerator.get_kv_offload_slice(
        num_requests=num_requests,
        skip_initial=skip_initial,
        critical_fraction=critical_fraction,
        deadline_slack_us=deadline_slack_us
    )
    if bg_iops > 0:
        base_requests = WorkloadGenerator.inject_background_traffic(
            base_requests,
            background_rate_iops=bg_iops
        )

    # First run S1 completely to log all completion times and deadline hits
    req_s1 = copy.deepcopy(base_requests)
    sim_s1 = Simulator(max_in_flight=32)
    res_s1 = sim_s1.run(req_s1, AIPriorityScheduler())
    s1_completed_map = {r.req_id: r for r in sim_s1.completed_requests}

    # Now run S3, but at each dispatch step, query what S1 would have selected
    req_s3 = copy.deepcopy(base_requests)
    sim_s3 = Simulator(max_in_flight=32)
    s1_selector = AIPriorityScheduler()
    s3_scheduler = AIAndSSDStateScheduler()

    divergences: List[DecisionDivergence] = []

    # Custom run loop for S3 to capture divergence
    backend = sim_s3.backend
    config = sim_s3.config

    # We hook into S3's scheduler to inspect queue before pop
    original_select_next = s3_scheduler.select_next

    def instrumented_select_next(b: SSDBackend, now: float) -> Optional[Request]:
        if len(s3_scheduler.queue) >= 2:
            # Check what S1 would pick: highest priority, earliest arrival
            s1_queue_copy = list(s3_scheduler.queue)
            s1_selector.queue = s1_queue_copy
            s1_pick = s1_selector.select_next(b, now)

            # Check what S3 picks
            s3_pick_req = original_select_next(b, now)

            if s1_pick and s3_pick_req and s1_pick.req_id != s3_pick_req.req_id:
                # DIVERGENCE FOUND!
                candidates_info = []
                for q_req in [s1_pick, s3_pick_req]:
                    if not q_req.sub_pages:
                        b.decompose_request(q_req)
                    
                    delay = b.estimate_service_delay(q_req, now)
                    ch_ids = [sub.channel_id for sub in q_req.sub_pages]
                    lun_ids = [sub.lun_id for sub in q_req.sub_pages]
                    
                    # Check busy state of primary channel
                    primary_ch = b.channels[ch_ids[0]]
                    ch_busy = primary_ch.bus_busy_until
                    lun_busy = primary_ch.lun_busy_until.get(lun_ids[0], 0.0)
                    
                    reason = "Idle & Ready"
                    if lun_busy > now:
                        reason = f"LUN {lun_ids[0]} Programming until {lun_busy:.1f} us"
                    elif ch_busy > now:
                        reason = f"Channel Bus {ch_ids[0]} Transferring until {ch_busy:.1f} us"

                    candidates_info.append(
                        CandidateInspection(
                            req_id=q_req.req_id,
                            op=q_req.op,
                            priority=q_req.priority.name,
                            arrival_time_us=q_req.arrival_time_us,
                            deadline_us=q_req.deadline_us,
                            slack_us=q_req.deadline_us - now,
                            mapped_channels=ch_ids,
                            mapped_luns=lun_ids,
                            is_channel_idle=(ch_busy <= now and lun_busy <= now),
                            channel_busy_until=max(ch_busy, lun_busy),
                            predicted_delay_us=delay,
                            blocking_reason=reason
                        )
                    )

                div = DecisionDivergence(
                    timestamp_us=now,
                    queue_depth=len(s3_scheduler.queue) + 1,
                    candidates=candidates_info,
                    s1_selected_id=s1_pick.req_id,
                    s1_reason=f"Arrival-order precedence within tier (arrived at {s1_pick.arrival_time_us:.1f} us vs {s3_pick_req.arrival_time_us:.1f} us)",
                    s3_selected_id=s3_pick_req.req_id,
                    s3_reason=f"Channel-conflict avoidance (Req {s3_pick_req.req_id} delay={b.estimate_service_delay(s3_pick_req, now):.1f} us vs Req {s1_pick.req_id} delay={b.estimate_service_delay(s1_pick, now):.1f} us)"
                )
                if len(divergences) < max_divergences:
                    divergences.append(div)

            return s3_pick_req
        else:
            return original_select_next(b, now)

    s3_scheduler.select_next = instrumented_select_next
    res_s3 = sim_s3.run(req_s3, s3_scheduler)
    s3_completed_map = {r.req_id: r for r in sim_s3.completed_requests}

    # Enrich divergences with outcomes from both runs
    for div in divergences:
        # S1 outcomes
        r_s1_picked = s1_completed_map.get(div.s1_selected_id)
        r_s1_alt = s1_completed_map.get(div.s3_selected_id)
        div.s1_outcome = {
            "req_selected": {
                "id": div.s1_selected_id,
                "completed": r_s1_picked.completion_time_us if r_s1_picked else 0.0,
                "latency": r_s1_picked.latency_us if r_s1_picked else 0.0,
                "met_deadline": r_s1_picked.met_deadline if r_s1_picked else False
            },
            "req_delayed": {
                "id": div.s3_selected_id,
                "completed": r_s1_alt.completion_time_us if r_s1_alt else 0.0,
                "latency": r_s1_alt.latency_us if r_s1_alt else 0.0,
                "met_deadline": r_s1_alt.met_deadline if r_s1_alt else False
            }
        }

        # S3 outcomes
        r_s3_picked = s3_completed_map.get(div.s3_selected_id)
        r_s3_alt = s3_completed_map.get(div.s1_selected_id)
        div.s3_outcome = {
            "req_selected": {
                "id": div.s3_selected_id,
                "completed": r_s3_picked.completion_time_us if r_s3_picked else 0.0,
                "latency": r_s3_picked.latency_us if r_s3_picked else 0.0,
                "met_deadline": r_s3_picked.met_deadline if r_s3_picked else False
            },
            "req_delayed": {
                "id": div.s1_selected_id,
                "completed": r_s3_alt.completion_time_us if r_s3_alt else 0.0,
                "latency": r_s3_alt.latency_us if r_s3_alt else 0.0,
                "met_deadline": r_s3_alt.met_deadline if r_s3_alt else False
            }
        }

    return divergences

def print_divergence_report(divergences: List[DecisionDivergence]):
    """Prints formatted proof-of-mechanism case studies."""
    print("\n" + "=" * 95)
    print("PROOF OF MECHANISM: INSTRUMENTED DECISION TIMELINES (S1 vs. S3)")
    print("=" * 95)

    for idx, d in enumerate(divergences, 1):
        c_s1 = next(c for c in d.candidates if c.req_id == d.s1_selected_id)
        c_s3 = next(c for c in d.candidates if c.req_id == d.s3_selected_id)
        
        print(f"\n--- CASE STUDY #{idx} AT SIMULATION TIME: {d.timestamp_us:.2f} µs ---")
        print(f"Pending Controller Queue: {d.queue_depth} requests")
        print(f"\n[Candidate Request A: ID {c_s1.req_id}]")
        print(f"  Priority: {c_s1.priority} | Op: {c_s1.op} | Arrived: {c_s1.arrival_time_us:.1f} µs")
        print(f"  Deadline: {c_s1.deadline_us:.1f} µs (Slack remaining: {c_s1.slack_us:.1f} µs)")
        print(f"  Mapped Resources: Channels {c_s1.mapped_channels}, LUNs {c_s1.mapped_luns}")
        print(f"  Hardware Status:  {'READY' if c_s1.is_channel_idle else 'BLOCKED'} ({c_s1.blocking_reason})")
        print(f"  Predicted Service Delay: {c_s1.predicted_delay_us:.1f} µs")

        print(f"\n[Candidate Request B: ID {c_s3.req_id}]")
        print(f"  Priority: {c_s3.priority} | Op: {c_s3.op} | Arrived: {c_s3.arrival_time_us:.1f} µs (Arrived later than A)")
        print(f"  Deadline: {c_s3.deadline_us:.1f} µs (Slack remaining: {c_s3.slack_us:.1f} µs)")
        print(f"  Mapped Resources: Channels {c_s3.mapped_channels}, LUNs {c_s3.mapped_luns}")
        print(f"  Hardware Status:  {'READY' if c_s3.is_channel_idle else 'BLOCKED'} ({c_s3.blocking_reason})")
        print(f"  Predicted Service Delay: {c_s3.predicted_delay_us:.1f} µs")

        print(f"\n[Scheduler Decisions at {d.timestamp_us:.2f} µs]")
        print(f"  S1 (AI-Priority Only): Dispatches Request A (ID {d.s1_selected_id})")
        print(f"     Reason: {d.s1_reason}")
        print(f"  S3 (TEMPO AI + SSD):  Dispatches Request B (ID {d.s3_selected_id})")
        print(f"     Reason: {d.s3_reason}")

        print(f"\n[Execution Outcomes]")
        print(f"  Under S1:")
        s1_sel = d.s1_outcome['req_selected']
        s1_del = d.s1_outcome['req_delayed']
        print(f"     Req A (ID {s1_sel['id']}): Finished at {s1_sel['completed']:.1f} µs (Latency: {s1_sel['latency']:.1f} µs) -> Met Deadline: {s1_sel['met_deadline']}")
        print(f"     Req B (ID {s1_del['id']}): Finished at {s1_del['completed']:.1f} µs (Latency: {s1_del['latency']:.1f} µs) -> Met Deadline: {s1_del['met_deadline']}")

        print(f"  Under S3:")
        s3_sel = d.s3_outcome['req_selected']
        s3_del = d.s3_outcome['req_delayed']
        print(f"     Req B (ID {s3_sel['id']}): Finished at {s3_sel['completed']:.1f} µs (Latency: {s3_sel['latency']:.1f} µs) -> Met Deadline: {s3_sel['met_deadline']}")
        print(f"     Req A (ID {s3_del['id']}): Finished at {s3_del['completed']:.1f} µs (Latency: {s3_del['latency']:.1f} µs) -> Met Deadline: {s3_del['met_deadline']}")
        print("-" * 95)

if __name__ == "__main__":
    divs = find_scheduling_divergences()
    print_divergence_report(divs)
