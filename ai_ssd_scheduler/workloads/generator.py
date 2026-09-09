"""Workload generators and trace slice extractors."""

import os
from typing import List, Optional
import numpy as np
from .parser import CheopsTraceParser
from .annotator import AIAnnotator
from ..ssd.request import Request, Priority

class WorkloadGenerator:
    """Manages workload extraction from CHEOPS traces with controlled contention."""

    DEFAULT_KV_TRACE = os.path.join(
        "temp_cheops",
        "results",
        "figure5-6-kv-offloading-flexgen",
        "flexgen-kv-offload-opt-6.7b-bs-64-ext4-trace",
        "opt-6.7b-kv-offload-bs-64-ext4-bpftrace-block.txt"
    )

    @classmethod
    def get_kv_offload_slice(
        cls,
        trace_path: Optional[str] = None,
        num_requests: int = 5000,
        skip_initial: int = 67800,  # Skips warmup writes to enter active decode read/write phase
        critical_fraction: float = 0.4,
        deadline_slack_us: float = 1200.0,
        inter_arrival_scale: float = 1.0
    ) -> List[Request]:
        """
        Loads a slice from the FlexGen KV-cache trace where reads and writes coexist.
        Applies AI semantic annotations and optional arrival timing scaling.
        """
        path = trace_path or cls.DEFAULT_KV_TRACE
        requests = CheopsTraceParser.load_requests(
            path,
            max_requests=num_requests,
            skip_initial=skip_initial
        )
        
        if inter_arrival_scale != 1.0:
            for req in requests:
                req.arrival_time_us *= inter_arrival_scale
                
        requests = AIAnnotator.annotate(
            requests,
            critical_read_fraction=critical_fraction,
            deadline_slack_us=deadline_slack_us
        )
        return requests

    @classmethod
    def inject_background_traffic(
        cls,
        base_requests: List[Request],
        background_rate_iops: float = 500.0,
        size_bytes: int = 131072,
        jitter: bool = True
    ) -> List[Request]:
        """
        Injects background writes interleaved with the AI workload.
        When jitter=True, inter-arrival times follow an exponential (Poisson) distribution
        seeded by np.random, introducing realistic stochastic variance across seeds.
        """
        if not base_requests:
            return []
            
        t_start = base_requests[0].arrival_time_us
        t_end = base_requests[-1].arrival_time_us
        duration_s = (t_end - t_start) / 1e6
        
        if duration_s <= 0:
            return base_requests
            
        num_bg = int(background_rate_iops * duration_s)
        mean_interval_us = (duration_s * 1e6) / max(1, num_bg)
        
        bg_requests: List[Request] = []
        cur_t = t_start
        base_sector = 100000000  # distinct LBA space
        
        for i in range(num_bg):
            if jitter:
                # Stochastic exponential inter-arrival (Poisson process)
                delta_t = float(np.random.exponential(scale=mean_interval_us))
                cur_t += delta_t
            else:
                cur_t += mean_interval_us
            bg_req = Request(
                req_id=9000000 + i,
                arrival_time_us=cur_t,
                op='W',
                size_bytes=size_bytes,
                start_sector=base_sector + (i * 256),
                num_sectors=256,
                priority=Priority.BACKGROUND,
                deadline_us=cur_t + 100000.0  # 100ms
            )
            bg_requests.append(bg_req)
            
        combined = base_requests + bg_requests
        combined.sort(key=lambda r: r.arrival_time_us)
        # Re-index req_ids
        for idx, req in enumerate(combined):
            req.req_id = idx
            
        return combined
