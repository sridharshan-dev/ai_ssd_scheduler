"""Request data structures and sub-page definitions."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple

class Priority(IntEnum):
    CRITICAL = 3
    NORMAL = 2
    BACKGROUND = 1

    @classmethod
    def from_str(cls, label: str) -> "Priority":
        val = label.strip().upper()
        if val in ("CRITICAL", "HIGH", "3"):
            return cls.CRITICAL
        elif val in ("NORMAL", "MEDIUM", "2"):
            return cls.NORMAL
        elif val in ("BACKGROUND", "LOW", "1"):
            return cls.BACKGROUND
        return cls.NORMAL

@dataclass
class PageSubRequest:
    """Individual 32 KiB flash page unit of a host request."""
    sub_id: int
    channel_id: int
    lun_id: int
    page_bytes: int
    is_write: bool

@dataclass
class Request:
    """High-level host I/O request."""
    req_id: int
    arrival_time_us: float
    op: str  # 'R' (read) or 'W' (write)
    size_bytes: int
    start_sector: int
    num_sectors: int
    priority: Priority = Priority.NORMAL
    deadline_us: float = 0.0
    
    # Sub-requests mapped to channels and LUNs
    sub_pages: List[PageSubRequest] = field(default_factory=list)
    
    # Execution timestamps
    dispatched_time_us: Optional[float] = None
    completion_time_us: Optional[float] = None

    @property
    def is_write(self) -> bool:
        return 'W' in self.op

    @property
    def latency_us(self) -> float:
        if self.completion_time_us is not None:
            return self.completion_time_us - self.arrival_time_us
        return 0.0

    @property
    def met_deadline(self) -> bool:
        if self.deadline_us <= 0.0 or self.completion_time_us is None:
            return True
        return self.completion_time_us <= self.deadline_us

    @property
    def deadline_slack_us(self) -> float:
        """Remaining time before deadline."""
        return self.deadline_us - self.arrival_time_us
