"""Abstract Base Scheduler."""

from abc import ABC, abstractmethod
from typing import List, Optional
from ..ssd.request import Request
from ..ssd.backend import SSDBackend

class BaseScheduler(ABC):
    """Abstract interface for SSD request scheduling algorithms."""
    def __init__(self, name: str):
        self.name = name
        self.queue: List[Request] = []

    def enqueue(self, req: Request, now: float):
        """Adds a newly arrived request to the pending queue."""
        self.queue.append(req)

    @abstractmethod
    def select_next(self, backend: SSDBackend, now: float) -> Optional[Request]:
        """Picks the next request to dispatch from the queue."""
        pass

    def on_request_completed(self, req: Request, now: float):
        """Hook called when a dispatched request completes on the SSD."""
        pass

    def is_empty(self) -> bool:
        return len(self.queue) == 0

    def queue_len(self) -> int:
        return len(self.queue)
