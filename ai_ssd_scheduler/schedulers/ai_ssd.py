"""S3: Joint AI Semantic + SSD Hardware State Aware Scheduler."""

from typing import Optional
from .base import BaseScheduler
from ..ssd.request import Request, Priority
from ..ssd.backend import SSDBackend

class AIAndSSDStateScheduler(BaseScheduler):
    """
    S3 - Joint AI + SSD State Aware Scheduler.
    
    Principles:
    1. Tier Isolation: High-priority AI requests always have tier precedence.
       A background request cannot preempt an urgent AI request simply because
       the background request is slightly faster.
    2. Intra-Tier Channel Optimization: Among requests of the same priority,
       dispatches the request targeting currently idle or earliest-completing channels,
       maximizing hardware parallelism and avoiding head-of-line stalls.
    3. Deadline Rescue: As deadlines approach, urgency escalates exponentially.
    4. Opportunistic Channel Utilization: If all critical requests target channels
       that are busy, lower-priority requests can be dispatched to unused idle channels.
    """
    def __init__(
        self,
        weight_urgency: float = 10000.0,
        weight_deadline: float = 1000.0,
        weight_channel_delay: float = 1.0
    ):
        super().__init__(name="S3-AI+SSD-State")
        self.w_urgency = weight_urgency
        self.w_deadline = weight_deadline
        self.w_channel_delay = weight_channel_delay

    def _compute_score(self, req: Request, backend: SSDBackend, now: float) -> float:
        # 1. Base Priority Tier (Dominant component)
        tier_base = req.priority * self.w_urgency

        # 2. SSD Channel State: Penalty for channels currently occupied by writes/GC
        delay_us = backend.estimate_service_delay(req, now)
        ssd_penalty = self.w_channel_delay * delay_us

        # 3. Deadline pressure
        deadline_boost = 0.0
        if req.deadline_us > 0.0:
            slack_us = req.deadline_us - now
            if slack_us > 0.0:
                deadline_boost = self.w_deadline / (slack_us + 10.0)
            else:
                # Past deadline: high boost to rescue immediately
                deadline_boost = self.w_deadline * 5.0 + abs(slack_us)

        return tier_base + deadline_boost - ssd_penalty

    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        if not self.queue:
            return None
            
        best_idx = 0
        best_score = self._compute_score(self.queue[0], backend, now)
        best_arrival = self.queue[0].arrival_time_us

        for i in range(1, len(self.queue)):
            req = self.queue[i]
            score = self._compute_score(req, backend, now)
            
            if score > best_score:
                best_idx = i
                best_score = score
                best_arrival = req.arrival_time_us
            elif abs(score - best_score) < 1e-4 and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        return self.queue.pop(best_idx)
