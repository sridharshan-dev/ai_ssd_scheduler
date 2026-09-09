"""S1: AI Semantic Priority Scheduler."""

from typing import Optional
from .base import BaseScheduler
from ..ssd.request import Request
from ..ssd.backend import SSDBackend

class AIPriorityScheduler(BaseScheduler):
    """
    S1 - AI Priority Queue.
    Selects the request with the highest AI priority (CRITICAL > NORMAL > BACKGROUND).
    Ties are broken in FIFO arrival order.
    Ignores internal SSD hardware state.
    """
    def __init__(self):
        super().__init__(name="S1-AI-Priority")

    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        if not self.queue:
            return None
            
        # Best item has highest priority int, then lowest arrival_time_us (earliest arrival)
        best_idx = 0
        best_priority = self.queue[0].priority
        best_arrival = self.queue[0].arrival_time_us

        for i in range(1, len(self.queue)):
            req = self.queue[i]
            if req.priority > best_priority:
                best_idx = i
                best_priority = req.priority
                best_arrival = req.arrival_time_us
            elif req.priority == best_priority and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        return self.queue.pop(best_idx)
