"""Channel and LUN hardware state tracking."""

from typing import Dict, Tuple
from .nand import SSDConfig

class Channel:
    """Represents a NAND channel and its attached LUNs (dies)."""
    def __init__(self, channel_id: int, luns_per_channel: int):
        self.channel_id = channel_id
        self.luns_per_channel = luns_per_channel
        self.bus_busy_until: float = 0.0
        # Map lun_id -> busy_until timestamp (us)
        self.lun_busy_until: Dict[int, float] = {i: 0.0 for i in range(luns_per_channel)}

    def is_bus_idle(self, now: float) -> bool:
        return self.bus_busy_until <= now

    def is_lun_idle(self, lun_id: int, now: float) -> bool:
        return self.lun_busy_until.get(lun_id, 0.0) <= now

    def earliest_ready_time(self, now: float, lun_id: int, is_write: bool, page_bytes: int, config: SSDConfig) -> Tuple[float, float]:
        """
        Calculates predicted (bus_start_time, completion_time) without mutating state.
        
        NAND Read Pipeline:
        1. LUN sensing: Begins at max(now, lun_busy_until). Takes t_read_us.
        2. Channel bus transfer: Begins at max(lun_sense_done, bus_busy_until). Takes xfer_time.
        3. Completion: when bus transfer ends + firmware overhead.
        
        NAND Write Pipeline:
        1. Channel bus transfer: Begins at max(now, bus_busy_until). Takes xfer_time.
        2. LUN program: Begins at max(bus_xfer_done, lun_busy_until). Takes t_prog_us.
        3. Completion: when LUN program ends (or when DMA ACKed, but media completion is program end).
        """
        xfer_time = config.transfer_time_us(page_bytes)
        lun_available = self.lun_busy_until.get(lun_id, 0.0)
        
        if not is_write:
            # READ
            sense_start = max(now, lun_available)
            sense_done = sense_start + config.t_read_us
            bus_start = max(sense_done, self.bus_busy_until)
            bus_done = bus_start + xfer_time
            completion_time = bus_done + config.t_fw_us
            return bus_start, completion_time
        else:
            # WRITE
            bus_start = max(now, self.bus_busy_until)
            bus_done = bus_start + xfer_time
            prog_start = max(bus_done, lun_available)
            prog_done = prog_start + config.t_prog_us
            completion_time = prog_done + config.t_fw_us
            return bus_start, completion_time

    def commit_page_service(self, now: float, lun_id: int, is_write: bool, page_bytes: int, config: SSDConfig) -> float:
        """Commits the page operation, advancing channel bus and LUN busy timers. Returns completion_time."""
        xfer_time = config.transfer_time_us(page_bytes)
        lun_available = self.lun_busy_until.get(lun_id, 0.0)
        
        if not is_write:
            # READ
            sense_start = max(now, lun_available)
            sense_done = sense_start + config.t_read_us
            bus_start = max(sense_done, self.bus_busy_until)
            bus_done = bus_start + xfer_time
            completion_time = bus_done + config.t_fw_us
            
            self.lun_busy_until[lun_id] = sense_done
            self.bus_busy_until = bus_done
            return completion_time
        else:
            # WRITE
            bus_start = max(now, self.bus_busy_until)
            bus_done = bus_start + xfer_time
            prog_start = max(bus_done, lun_available)
            prog_done = prog_start + config.t_prog_us
            completion_time = prog_done + config.t_fw_us
            
            self.bus_busy_until = bus_done
            self.lun_busy_until[lun_id] = prog_done
            return completion_time

    def inject_background_delay(self, lun_id: int, duration_us: float, now: float):
        """Simulate background GC, wear-leveling, or scrubber locking a LUN."""
        current_busy = max(now, self.lun_busy_until.get(lun_id, 0.0))
        self.lun_busy_until[lun_id] = current_busy + duration_us
