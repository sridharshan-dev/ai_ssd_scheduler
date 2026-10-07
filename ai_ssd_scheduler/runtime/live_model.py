"""Convert live model-runtime events into TEMPO request urgency metadata."""

from enum import Enum
from typing import Optional

from ..ssd.request import Priority, Request


class RuntimePhase(str, Enum):
    PREFILL = "PREFILL"
    DECODE = "DECODE"
    CHECKPOINT = "CHECKPOINT"
    SYNC = "SYNC"
    IDLE = "IDLE"


class LiveModelTelemetry:
    """Runtime-side adapter for live urgency and relative deadline signals.

    A model-serving or training integration calls ``set_phase`` at phase
    transitions and ``annotate_io`` when it submits an I/O request. The SSD
    scheduler then receives deadlines derived from the model SLA rather than
    from a fixed trace annotation pattern.
    """

    def __init__(self, token_sla_us: float = 800.0):
        if token_sla_us <= 0.0:
            raise ValueError("token_sla_us must be positive")
        self.token_sla_us = token_sla_us
        self.phase = RuntimePhase.IDLE
        self.phase_started_us = 0.0
        self.next_token_deadline_us: Optional[float] = None

    def set_phase(
        self,
        phase: RuntimePhase,
        now_us: float,
        token_sla_us: Optional[float] = None,
        next_token_deadline_us: Optional[float] = None,
    ) -> None:
        """Publish a phase transition from the live model runtime."""
        if token_sla_us is not None:
            if token_sla_us <= 0.0:
                raise ValueError("token_sla_us must be positive")
            self.token_sla_us = token_sla_us
        self.phase = phase
        self.phase_started_us = now_us
        self.next_token_deadline_us = next_token_deadline_us

    def annotate_io(self, request: Request, now_us: float) -> Request:
        """Attach runtime-derived priority and absolute deadline to a request."""
        request.data_class = self._data_class_for_phase(request)
        request.classification_confidence = 1.0

        if self.phase == RuntimePhase.DECODE and not request.is_write:
            request.priority = Priority.CRITICAL
            deadline = self.next_token_deadline_us
            if deadline is None:
                deadline = now_us + self.token_sla_us
        elif self.phase == RuntimePhase.SYNC:
            request.priority = Priority.CRITICAL
            deadline = now_us + min(self.token_sla_us, 250.0)
        elif self.phase == RuntimePhase.CHECKPOINT:
            request.priority = Priority.BACKGROUND
            deadline = now_us + 100000.0
        elif self.phase == RuntimePhase.PREFILL:
            request.priority = Priority.NORMAL
            deadline = now_us + self.token_sla_us * 4.0
        else:
            request.priority = Priority.BACKGROUND
            deadline = now_us + 100000.0

        request.deadline_us = deadline
        return request

    def _data_class_for_phase(self, request: Request) -> str:
        if self.phase == RuntimePhase.DECODE and not request.is_write:
            return "KV_CACHE"
        if self.phase == RuntimePhase.CHECKPOINT and request.is_write:
            return "OPTIMIZER_CHECKPOINT"
        if self.phase == RuntimePhase.PREFILL and not request.is_write:
            return "MODEL_WEIGHTS"
        return "UNKNOWN"
