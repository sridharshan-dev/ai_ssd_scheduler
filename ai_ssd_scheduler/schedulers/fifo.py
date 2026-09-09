"""S0: First-In First-Out (Baseline)."""

from typing import Optional
from .base import BaseScheduler
from ..ssd.request import Request
from ..ssd.backend import SSDBackend

class FIFOScheduler(BaseScheduler):
    """
    S0 - Standard FIFO baseline.
    Dispatches requests strictly in arrival order with zero AI or SSD state awareness.
    """
    def __init__(self):
        super().__init__(name="S0-FIFO")

    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        if not self.queue:
            return None
        return self.queue.pop(0)
