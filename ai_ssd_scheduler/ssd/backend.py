"""SSD Backend Controller modeling multi-channel striping and execution."""

import math
from typing import Dict, List, Tuple
from .nand import SSDConfig
from .channel import Channel
from .request import Request, PageSubRequest

class SSDBackend:
    """Represents the SSD controller, channels, and LUNs."""
    def __init__(self, config: SSDConfig = SSDConfig()):
        self.config = config
        self.channels: List[Channel] = [
            Channel(i, config.luns_per_channel) for i in range(config.num_channels)
        ]
        self.pool_page_counts: Dict[str, int] = {}

    @staticmethod
    def select_placement_pool(req: Request) -> str:
        """Map inferred lifetime classes to explicit FTL placement pools."""
        return {
            "KV_CACHE": "PSLC_HOT",
            "OPTIMIZER_CHECKPOINT": "STRIPED_QLC",
            "MODEL_WEIGHTS": "ISOLATED_QLC",
            "TRAINING_SAMPLE": "READ_OPTIMIZED",
        }.get(req.data_class, "DEFAULT")

    def decompose_request(self, req: Request) -> List[PageSubRequest]:
        """Stripes a host request across channels and LUNs in 32 KiB page chunks."""
        req.placement_pool = self.select_placement_pool(req)
        page_size = self.config.page_size_bytes
        sectors_per_page = page_size // self.config.sector_size_bytes
        base_page = req.start_sector // sectors_per_page
        
        num_pages = max(1, math.ceil(req.size_bytes / page_size))
        sub_requests = []
        
        remaining_bytes = req.size_bytes
        for p in range(num_pages):
            page_bytes = min(page_size, remaining_bytes)
            global_page_id = base_page + p
            # Striping: channel = global_page % num_channels
            channel_id = global_page_id % self.config.num_channels
            # LUN interleaving
            lun_id = (global_page_id // self.config.num_channels) % self.config.luns_per_channel
            
            sub_requests.append(
                PageSubRequest(
                    sub_id=p,
                    channel_id=channel_id,
                    lun_id=lun_id,
                    page_bytes=page_bytes,
                    is_write=req.is_write
                )
            )
            remaining_bytes -= page_bytes

        self.pool_page_counts[req.placement_pool] = (
            self.pool_page_counts.get(req.placement_pool, 0) + len(sub_requests)
        )
            
        req.sub_pages = sub_requests
        return sub_requests

    def predict_request_completion(self, req: Request, now: float) -> float:
        """
        Estimates the completion timestamp for the request if dispatched at 'now',
        without altering channel state. The slowest sub-page dictates completion.
        """
        if not req.sub_pages:
            self.decompose_request(req)
            
        max_completion = now
        for sub in req.sub_pages:
            ch = self.channels[sub.channel_id]
            _, page_done = ch.earliest_ready_time(
                now=now,
                lun_id=sub.lun_id,
                is_write=sub.is_write,
                page_bytes=sub.page_bytes,
                config=self.config
            )
            if page_done > max_completion:
                max_completion = page_done
                
        return max_completion

    def estimate_service_delay(self, req: Request, now: float) -> float:
        """Returns the predicted wait/service duration (predicted_completion - now)."""
        completion = self.predict_request_completion(req, now)
        return max(0.0, completion - now)

    def dispatch_request(self, req: Request, now: float) -> float:
        """
        Commits all sub-pages of the request to their respective channels and LUNs.
        Returns the overall request completion timestamp (us).
        """
        if not req.sub_pages:
            self.decompose_request(req)
            
        req.dispatched_time_us = now
        max_completion = now
        
        for sub in req.sub_pages:
            ch = self.channels[sub.channel_id]
            sub_done = ch.commit_page_service(
                now=now,
                lun_id=sub.lun_id,
                is_write=sub.is_write,
                page_bytes=sub.page_bytes,
                config=self.config
            )
            if sub_done > max_completion:
                max_completion = sub_done
                
        req.completion_time_us = max_completion
        return max_completion

    def get_channel_utilization(self, now: float) -> float:
        """Fraction of channels currently active."""
        busy_channels = sum(1 for ch in self.channels if not ch.is_bus_idle(now))
        return busy_channels / len(self.channels)

    def inject_gc_pause(self, channel_id: int, lun_id: int, duration_us: float, now: float):
        """Simulates a GC or wear-leveling pause on a specific LUN."""
        self.channels[channel_id].inject_background_delay(lun_id, duration_us, now)
