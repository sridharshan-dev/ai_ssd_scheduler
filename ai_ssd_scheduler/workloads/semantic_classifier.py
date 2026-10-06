"""Trace-observable semantic classification for AI SSD requests."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, Optional

from ..ssd.request import Request


class DataClass(str, Enum):
    """Storage-lifetime classes inferred from block-I/O behavior."""

    MODEL_WEIGHTS = "MODEL_WEIGHTS"
    OPTIMIZER_CHECKPOINT = "OPTIMIZER_CHECKPOINT"
    KV_CACHE = "KV_CACHE"
    TRAINING_SAMPLE = "TRAINING_SAMPLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Classification:
    data_class: DataClass
    confidence: float
    sequentiality: float
    overwrite_rate: float


class SemanticClassifier:
    """Small online classifier using only request shape and recent LBA history.

    This is intentionally explainable and controller-friendly. It is a baseline
    classifier, not a claim of production-grade model-independent accuracy.
    """

    def __init__(self, history_size: int = 256):
        self._recent_writes: Deque[int] = deque(maxlen=history_size)
        self._write_counts: Dict[int, int] = {}
        self._previous_end_sector: Optional[int] = None

    def classify(self, request: Request) -> Classification:
        start = request.start_sector
        end = start + request.num_sectors
        sequentiality = 1.0 if self._previous_end_sector == start else 0.0
        overwrite_rate = min(1.0, self._write_counts.get(start, 0) / 3.0)

        if request.is_write:
            if overwrite_rate > 0.0:
                data_class = DataClass.KV_CACHE
                confidence = min(0.95, 0.65 + overwrite_rate * 0.3)
            elif sequentiality > 0.0 and request.size_bytes >= 128 * 1024:
                data_class = DataClass.OPTIMIZER_CHECKPOINT
                confidence = 0.72
            else:
                data_class = DataClass.UNKNOWN
                confidence = 0.35
        elif request.size_bytes >= 1024 * 1024 and sequentiality > 0.0:
            data_class = DataClass.MODEL_WEIGHTS
            confidence = 0.78
        elif sequentiality == 0.0:
            data_class = DataClass.TRAINING_SAMPLE
            confidence = 0.55
        else:
            data_class = DataClass.KV_CACHE
            confidence = 0.5

        return Classification(
            data_class=data_class,
            confidence=confidence,
            sequentiality=sequentiality,
            overwrite_rate=overwrite_rate,
        )

    def observe(self, request: Request, result: Classification) -> None:
        """Update online state after classifying a request."""
        if request.is_write:
            self._recent_writes.append(request.start_sector)
            self._write_counts[request.start_sector] = self._write_counts.get(request.start_sector, 0) + 1
        self._previous_end_sector = request.start_sector + request.num_sectors
