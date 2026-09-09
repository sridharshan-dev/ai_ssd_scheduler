"""SSD hardware and NAND timing configuration based on NVMeVirt (Samsung 970 Pro)."""

from dataclasses import dataclass

@dataclass(frozen=True)
class SSDConfig:
    """Hardware geometry and timing parameters."""
    num_channels: int = 8
    luns_per_channel: int = 2
    page_size_bytes: int = 32 * 1024  # 32 KiB flash page
    channel_bandwidth_mb_s: float = 800.0  # 800 MB/s per channel
    
    # Timing parameters in microseconds (us)
    t_read_us: float = 36.0        # NAND flash page read latency (tR)
    t_prog_us: float = 185.0       # NAND flash page program latency (tPROG)
    t_fw_us: float = 30.5          # Controller/firmware processing overhead
    
    # Sector size
    sector_size_bytes: int = 512

    @property
    def total_luns(self) -> int:
        return self.num_channels * self.luns_per_channel

    @property
    def channel_bandwidth_bytes_per_us(self) -> float:
        """800 MB/s = 800 * 10^6 bytes/s = 800 bytes/us."""
        return self.channel_bandwidth_mb_s

    def transfer_time_us(self, bytes_count: int) -> float:
        """Bus transfer time over a single NAND channel in microseconds."""
        return bytes_count / self.channel_bandwidth_bytes_per_us
