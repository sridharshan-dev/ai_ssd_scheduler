"""Discrete-Event SSD Simulator Engine."""

import heapq
import numpy as np
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Dict, Any, Optional
from .nand import SSDConfig
from .backend import SSDBackend
from .request import Request, Priority
from ..schedulers.base import BaseScheduler

class EventType(IntEnum):
    ARRIVAL = 1
    COMPLETION = 2
    GC_EVENT = 3

@dataclass(order=True)
class SimEvent:
    timestamp: float
    event_id: int
    event_type: EventType = field(compare=False)
    payload: Any = field(compare=False)

@dataclass
class SimulationResult:
    scheduler_name: str
    total_requests: int
    critical_requests: int
    normal_requests: int
    background_requests: int
    elapsed_time_ms: float
    throughput_mb_s: float
    iops: float
    
    # Latencies in microseconds (all requests)
    p50_latency_us: float
    p90_latency_us: float
    p95_latency_us: float
    p99_latency_us: float
    p99_9_latency_us: float
    max_latency_us: float
    
    # Critical AI request latencies
    critical_p50_us: float
    critical_p90_us: float
    critical_p95_us: float
    critical_p99_us: float
    critical_p99_9_us: float
    critical_max_us: float
    
    # Deadline miss stats
    critical_deadline_misses: int
    critical_deadline_miss_pct: float
    
    def print_summary(self):
        print(f"=== Simulation Result: {self.scheduler_name} ===")
        print(f"  Total Requests: {self.total_requests} (Critical: {self.critical_requests})")
        print(f"  Duration: {self.elapsed_time_ms:.2f} ms | Throughput: {self.throughput_mb_s:.2f} MB/s | IOPS: {self.iops:.1f}")
        print(f"  All Latency (us)      -> P50: {self.p50_latency_us:.1f}, P95: {self.p95_latency_us:.1f}, P99: {self.p99_latency_us:.1f}, Max: {self.max_latency_us:.1f}")
        print(f"  Critical Latency (us)  -> P50: {self.critical_p50_us:.1f}, P95: {self.critical_p95_us:.1f}, P99: {self.critical_p99_us:.1f}, Max: {self.critical_max_us:.1f}")
        print(f"  Critical Deadline Misses: {self.critical_deadline_misses} / {self.critical_requests} ({self.critical_deadline_miss_pct:.2f}%)")
        print("=" * 48)

class Simulator:
    """Discrete-event simulator orchestrating Arrivals, Scheduling, and SSD Execution."""
    def __init__(
        self,
        config: SSDConfig = SSDConfig(),
        max_in_flight: int = 32
    ):
        self.config = config
        self.max_in_flight = max_in_flight
        self.backend = SSDBackend(config)
        self.event_queue: List[SimEvent] = []
        self.event_counter = 0
        self.current_time_us = 0.0
        self.in_flight_count = 0
        self.completed_requests: List[Request] = []

    def schedule_event(self, timestamp: float, event_type: EventType, payload: Any):
        self.event_counter += 1
        heapq.heappush(
            self.event_queue,
            SimEvent(timestamp=timestamp, event_id=self.event_counter, event_type=event_type, payload=payload)
        )

    def _try_dispatch(self, scheduler: BaseScheduler):
        """Dispatches ready requests from scheduler queue up to max in-flight limit."""
        while self.in_flight_count < self.max_in_flight and not scheduler.is_empty():
            next_req = scheduler.select_next(self.backend, self.current_time_us)
            if next_req is None:
                break
                
            self.in_flight_count += 1
            completion_us = self.backend.dispatch_request(next_req, self.current_time_us)
            self.schedule_event(completion_us, EventType.COMPLETION, next_req)

    def run(
        self,
        requests: List[Request],
        scheduler: BaseScheduler,
        gc_events: Optional[List[tuple]] = None
    ) -> SimulationResult:
        """
        Executes the discrete-event simulation.
        gc_events is an optional list of (timestamp_us, channel_id, lun_id, duration_us).
        """
        # Deep reset
        self.backend = SSDBackend(self.config)
        self.event_queue = []
        self.event_counter = 0
        self.current_time_us = 0.0
        self.in_flight_count = 0
        self.completed_requests = []
        
        # Schedule all request arrivals
        for req in requests:
            self.schedule_event(req.arrival_time_us, EventType.ARRIVAL, req)
            
        # Schedule any GC events
        if gc_events:
            for gc in gc_events:
                ts, ch, lun, dur = gc
                self.schedule_event(ts, EventType.GC_EVENT, (ch, lun, dur))

        # Event loop
        while self.event_queue:
            evt = heapq.heappop(self.event_queue)
            self.current_time_us = max(self.current_time_us, evt.timestamp)

            if evt.event_type == EventType.ARRIVAL:
                req: Request = evt.payload
                scheduler.enqueue(req, self.current_time_us)
                self._try_dispatch(scheduler)

            elif evt.event_type == EventType.COMPLETION:
                req: Request = evt.payload
                self.in_flight_count -= 1
                self.completed_requests.append(req)
                scheduler.on_request_completed(req, self.current_time_us)
                self._try_dispatch(scheduler)

            elif evt.event_type == EventType.GC_EVENT:
                ch, lun, dur = evt.payload
                self.backend.inject_gc_pause(ch, lun, dur, self.current_time_us)
                # Dispatch check in case new decisions need to be made
                self._try_dispatch(scheduler)

        # Compute summary metrics
        return self._build_result(scheduler.name)

    def _build_result(self, scheduler_name: str) -> SimulationResult:
        if not self.completed_requests:
            return SimulationResult(
                scheduler_name=scheduler_name,
                total_requests=0,
                critical_requests=0,
                normal_requests=0,
                background_requests=0,
                elapsed_time_ms=0.0,
                throughput_mb_s=0.0,
                iops=0.0,
                p50_latency_us=0.0,
                p90_latency_us=0.0,
                p95_latency_us=0.0,
                p99_latency_us=0.0,
                p99_9_latency_us=0.0,
                max_latency_us=0.0,
                critical_p50_us=0.0,
                critical_p90_us=0.0,
                critical_p95_us=0.0,
                critical_p99_us=0.0,
                critical_p99_9_us=0.0,
                critical_max_us=0.0,
                critical_deadline_misses=0,
                critical_deadline_miss_pct=0.0
            )

        all_latencies = np.array([r.latency_us for r in self.completed_requests])
        crit_reqs = [r for r in self.completed_requests if r.priority == Priority.CRITICAL]
        crit_latencies = np.array([r.latency_us for r in crit_reqs]) if crit_reqs else np.array([0.0])
        
        crit_misses = sum(1 for r in crit_reqs if not r.met_deadline)
        crit_miss_pct = (crit_misses / len(crit_reqs) * 100.0) if crit_reqs else 0.0

        total_bytes = sum(r.size_bytes for r in self.completed_requests)
        total_time_us = max(1.0, self.current_time_us)
        total_time_s = total_time_us / 1e6

        return SimulationResult(
            scheduler_name=scheduler_name,
            total_requests=len(self.completed_requests),
            critical_requests=len(crit_reqs),
            normal_requests=sum(1 for r in self.completed_requests if r.priority == Priority.NORMAL),
            background_requests=sum(1 for r in self.completed_requests if r.priority == Priority.BACKGROUND),
            elapsed_time_ms=total_time_us / 1000.0,
            throughput_mb_s=(total_bytes / (1024 * 1024)) / total_time_s,
            iops=len(self.completed_requests) / total_time_s,
            p50_latency_us=float(np.percentile(all_latencies, 50)),
            p90_latency_us=float(np.percentile(all_latencies, 90)),
            p95_latency_us=float(np.percentile(all_latencies, 95)),
            p99_latency_us=float(np.percentile(all_latencies, 99)),
            p99_9_latency_us=float(np.percentile(all_latencies, 99.9)),
            max_latency_us=float(np.max(all_latencies)),
            critical_p50_us=float(np.percentile(crit_latencies, 50)),
            critical_p90_us=float(np.percentile(crit_latencies, 90)),
            critical_p95_us=float(np.percentile(crit_latencies, 95)),
            critical_p99_us=float(np.percentile(crit_latencies, 99)),
            critical_p99_9_us=float(np.percentile(crit_latencies, 99.9)),
            critical_max_us=float(np.max(crit_latencies)),
            critical_deadline_misses=crit_misses,
            critical_deadline_miss_pct=crit_miss_pct
        )
