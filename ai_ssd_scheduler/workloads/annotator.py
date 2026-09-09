"""AI Semantic Annotation Layer (Controlled Experimental Variable)."""

from typing import List
from ..ssd.request import Request, Priority

class AIAnnotator:
    """
    Annotates raw block I/O requests with AI semantic urgency and target deadlines.
    
    NOTE: This is an explicit, controlled experimental variable testing the hypothesis
    that knowing AI importance enables superior SSD scheduling, not data measured
    by the block trace itself.
    """

    @staticmethod
    def annotate(
        requests: List[Request],
        critical_read_fraction: float = 0.4,
        deadline_slack_us: float = 800.0,
        normal_deadline_slack_us: float = 5000.0
    ) -> List[Request]:
        """
        Assigns Priority and deadlines:
        - Critical: Time-sensitive KV-cache reads required for active token decode.
        - Normal: Bulk model/weight streaming or standard KV update writes.
        - Background: File system metadata and sync flushes.
        """
        read_counter = 0
        
        for req in requests:
            # Metadata operations are naturally background
            if 'M' in req.op or 'S' in req.op:
                req.priority = Priority.BACKGROUND
                req.deadline_us = req.arrival_time_us + 50000.0  # 50 ms loose deadline
            elif not req.is_write:
                # Reads: Mark a deterministic fraction as Critical (e.g., active layer decode reads)
                if (read_counter % 10) < int(critical_read_fraction * 10):
                    req.priority = Priority.CRITICAL
                    req.deadline_us = req.arrival_time_us + deadline_slack_us
                else:
                    req.priority = Priority.NORMAL
                    req.deadline_us = req.arrival_time_us + normal_deadline_slack_us
                read_counter += 1
            else:
                # Standard writes (KV checkpoint / activation spill)
                req.priority = Priority.NORMAL
                req.deadline_us = req.arrival_time_us + normal_deadline_slack_us
                
        return requests
