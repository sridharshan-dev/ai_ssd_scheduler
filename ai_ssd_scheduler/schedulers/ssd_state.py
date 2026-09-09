"""S2: SSD-State-Aware Scheduler (Storage-Only Intelligence)."""

from typing import Optional
from .base import BaseScheduler
from ..ssd.request import Request
from ..ssd.backend import SSDBackend

class SSDStateScheduler(BaseScheduler):
    """
    S2 - SSD-State-Aware Scheduler.
    Selects the pending request whose target channels/LUNs can complete the earliest
    (lowest estimated service delay).
    Ignores AI semantics and urgency.
    """
    def __init__(self):
        super().__init__(name="S2-SSD-State")

    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        if not self.queue:
            return None
            
        best_idx = 0
        best_delay = backend.estimate_service_delay(self.queue[0], now)
        best_arrival = self.queue[0].arrival_time_us

        for i in range(1, len(self.queue)):
            req = self.queue[i]
            delay = backend.estimate_service_delay(req, now)
            
            # Prefer significantly smaller delay, tie-break by arrival
            if delay < best_delay - 1e-3:
                best_idx = i
                best_delay = delay
                best_arrival = req.arrival_time_us
            elif abs(delay - best_delay) <= 1e-3 and req.arrival_time_us < best_arrival:
                best_idx = i
                best_arrival = req.arrival_time_us

        return self.queue.pop(best_idx)
