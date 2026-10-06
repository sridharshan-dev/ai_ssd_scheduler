"""Online I/O-phase detector used to gate background SSD work."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

from ..ssd.request import Request


class WorkloadPhase(str, Enum):
    DATA_LOAD = "DATA_LOAD"
    COMPUTE = "COMPUTE"
    CHECKPOINT = "CHECKPOINT"
    SYNC = "SYNC"
    IDLE = "IDLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PhaseState:
    phase: WorkloadPhase
    confidence: float
    predicted_next: Optional[WorkloadPhase]


class PhaseDetector:
    """Classify recent I/O rhythm without host-side phase hints."""

    def __init__(self, window_size: int = 32, idle_timeout_us: float = 5000.0):
        self.window_size = window_size
        self.idle_timeout_us = idle_timeout_us
        self._events: Deque[Request] = deque(maxlen=window_size)
        self._last_event_us: Optional[float] = None
        self.state = PhaseState(WorkloadPhase.UNKNOWN, 0.0, None)

    def observe(self, request: Request, now_us: float) -> PhaseState:
        self._events.append(request)
        self._last_event_us = now_us
        writes = sum(1 for event in self._events if event.is_write)
        reads = len(self._events) - writes
        write_ratio = writes / len(self._events)
        critical_reads = sum(
            1 for event in self._events
            if not event.is_write and event.priority.name == "CRITICAL"
        )

        if write_ratio >= 0.5 and len(self._events) >= 4:
            phase = WorkloadPhase.CHECKPOINT
            confidence = min(0.95, 0.55 + write_ratio * 0.4)
        elif critical_reads >= max(2, len(self._events) // 3):
            phase = WorkloadPhase.SYNC
            confidence = min(0.9, 0.5 + critical_reads / len(self._events) * 0.4)
        elif reads > writes:
            phase = WorkloadPhase.DATA_LOAD
            confidence = 0.55
        else:
            phase = WorkloadPhase.COMPUTE
            confidence = 0.5

        self.state = PhaseState(phase, confidence, self._next_phase(phase))
        return self.state

    def current(self, now_us: float) -> PhaseState:
        if self._last_event_us is None or now_us - self._last_event_us >= self.idle_timeout_us:
            self.state = PhaseState(WorkloadPhase.IDLE, 0.9, WorkloadPhase.DATA_LOAD)
        return self.state

    def gc_allowed(self, now_us: float) -> bool:
        phase = self.current(now_us).phase
        return phase in (WorkloadPhase.COMPUTE, WorkloadPhase.IDLE, WorkloadPhase.UNKNOWN)

    @staticmethod
    def _next_phase(phase: WorkloadPhase) -> Optional[WorkloadPhase]:
        transitions = {
            WorkloadPhase.DATA_LOAD: WorkloadPhase.COMPUTE,
            WorkloadPhase.COMPUTE: WorkloadPhase.CHECKPOINT,
            WorkloadPhase.CHECKPOINT: WorkloadPhase.SYNC,
            WorkloadPhase.SYNC: WorkloadPhase.COMPUTE,
            WorkloadPhase.IDLE: WorkloadPhase.DATA_LOAD,
        }
        return transitions.get(phase)
