"""Ablation Schedulers for Phase 9: Isolating Individual SSD State Signals."""

from typing import Optional, List, Dict
from .base import BaseScheduler
from ..ssd.request import Request
from ..ssd.backend import SSDBackend

class AblationScheduler(BaseScheduler):
    """
    Modular scheduler that selectively enables:
    - AI Urgency (priority tier + deadline urgency)
    - Channel Readiness (penalizes channels currently occupied by active bus transfers or normal read/prog)
    - Channel Queue Depth (penalizes channels with high pending request count in the queue)
    - GC State (penalizes LUNs locked in long block-erase / GC cycles)
    """
    def __init__(
        self,
        name: str,
        enable_ai_urgency: bool = True,
        enable_channel_readiness: bool = False,
        enable_queue_depth: bool = False,
        enable_gc_state: bool = False,
        weight_urgency: float = 10000.0,
        weight_deadline: float = 1000.0,
        weight_channel: float = 1.0,
        weight_queue_depth: float = 50.0,
        weight_gc: float = 2.0
    ):
        super().__init__(name=name)
        self.enable_ai_urgency = enable_ai_urgency
        self.enable_channel_readiness = enable_channel_readiness
        self.enable_queue_depth = enable_queue_depth
        self.enable_gc_state = enable_gc_state
        
        self.w_urgency = weight_urgency
        self.w_deadline = weight_deadline
        self.w_channel = weight_channel
        self.w_queue_depth = weight_queue_depth
        self.w_gc = weight_gc

    def _compute_score(
        self,
        req: Request,
        backend: SSDBackend,
        now: float,
        channel_queue_counts: Dict[int, int]
    ) -> float:
        score = 0.0

        # 1. AI Urgency Component
        if self.enable_ai_urgency:
            tier_base = req.priority * self.w_urgency
            deadline_boost = 0.0
            if req.deadline_us > 0.0:
                slack_us = req.deadline_us - now
                if slack_us > 0.0:
                    deadline_boost = self.w_deadline / (slack_us + 10.0)
                else:
                    deadline_boost = self.w_deadline * 5.0 + abs(slack_us)
            score += (tier_base + deadline_boost)

        # Decompose sub-pages if not done
        if not req.sub_pages:
            backend.decompose_request(req)

        # 2. Channel Readiness Component (Bus / Normal Read/Prog execution)
        if self.enable_channel_readiness:
            # Measure delay caused by ongoing bus transfer or normal NAND program (< 500 us)
            ch_delay = 0.0
            for sub in req.sub_pages:
                ch = backend.channels[sub.channel_id]
                bus_wait = max(0.0, ch.bus_busy_until - now)
                lun_busy = ch.lun_busy_until.get(sub.lun_id, 0.0)
                lun_wait = max(0.0, lun_busy - now)
                # Cap lun_wait at standard program time so it doesn't conflate with GC erase
                capped_lun_wait = min(lun_wait, backend.config.t_prog_us)
                wait_time = max(bus_wait, capped_lun_wait)
                if wait_time > ch_delay:
                    ch_delay = wait_time
            score -= (self.w_channel * ch_delay)

        # 3. Queue Depth Component (Channel backlog contention)
        if self.enable_queue_depth:
            # Penalize requests targeting channels that have many pending sub-requests in queue
            max_qd = 0
            for sub in req.sub_pages:
                qd = channel_queue_counts.get(sub.channel_id, 0)
                if qd > max_qd:
                    max_qd = qd
            score -= (self.w_queue_depth * max_qd)

        # 4. GC State Component (Block erase stalls > t_prog)
        if self.enable_gc_state:
            # Detect whether any target die is locked in a GC / erase operation (> t_prog_us)
            gc_penalty = 0.0
            for sub in req.sub_pages:
                ch = backend.channels[sub.channel_id]
                lun_busy = ch.lun_busy_until.get(sub.lun_id, 0.0)
                lun_wait = max(0.0, lun_busy - now)
                # An active erase lock exceeds t_prog_us (e.g. 500 us to 3500 us)
                if lun_wait > backend.config.t_prog_us:
                    if lun_wait > gc_penalty:
                        gc_penalty = lun_wait
            score -= (self.w_gc * gc_penalty)

        return score

    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        if not self.queue:
            return None

        # Tally per-channel pending sub-requests across the current queue
        channel_counts: Dict[int, int] = {}
        if self.enable_queue_depth:
            for q_req in self.queue:
                if not q_req.sub_pages:
                    backend.decompose_request(q_req)
                for sub in q_req.sub_pages:
                    channel_counts[sub.channel_id] = channel_counts.get(sub.channel_id, 0) + 1

        best_idx = 0
        best_score = self._compute_score(self.queue[0], backend, now, channel_counts)
        best_arrival = self.queue[0].arrival_time_us

        for i in range(1, len(self.queue)):
            req = self.queue[i]
            score = self._compute_score(req, backend, now, channel_counts)

            if score > best_score:
                best_idx = i
                best_score = score
                best_arrival = req.arrival_time_us
            elif abs(score - best_score) < 1e-4 and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        return self.queue.pop(best_idx)
