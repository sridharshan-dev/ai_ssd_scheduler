"""Defensible SSD Energy Model grounded in Samsung 970 Pro NVMe specifications.

Power Specifications (Samsung 970 Pro / NVMeVirt validated):
- Active Read Power: 5.2 W
- Active Write Power: 5.7 W
- Active Controller Standby / Non-Operational: 0.5 W
- Low-Power Idle (L1.2 state): 0.03 W

Metrics Calculated:
- Total Energy (Joules)
- Energy per Request (mJ / req)
- Energy per Megabyte transferred (mJ / MB)
- Energy per Deadline-Satisfied Critical AI Request (mJ / successful req)
"""

from dataclasses import dataclass
from typing import List
from .request import Request, Priority

@dataclass
class EnergyProfile:
    total_energy_joules: float
    active_read_joules: float
    active_write_joules: float
    idle_standby_joules: float
    energy_per_request_mj: float
    energy_per_mb_mj: float
    energy_per_satisfied_critical_req_mj: float
    satisfied_critical_count: int
    total_critical_count: int

class SSDEnergyModel:
    def __init__(
        self,
        power_read_w: float = 5.2,
        power_write_w: float = 5.7,
        power_standby_w: float = 0.5,
        power_idle_w: float = 0.03
    ):
        self.power_read_w = power_read_w
        self.power_write_w = power_write_w
        self.power_standby_w = power_standby_w
        self.power_idle_w = power_idle_w

    def compute_energy(self, requests: List[Request], benchmark_duration_us: float) -> EnergyProfile:
        """
        Computes energy breakdown based on physical execution time of all served requests.
        """
        benchmark_sec = benchmark_duration_us / 1e6

        # Tally active execution times
        total_read_time_us = 0.0
        total_write_time_us = 0.0
        total_bytes = 0
        critical_satisfied = 0
        total_critical = 0

        for req in requests:
            duration_us = max(0.0, req.completion_time_us - req.dispatched_time_us)
            total_bytes += req.size_bytes
            if req.is_write:
                total_write_time_us += duration_us
            else:
                total_read_time_us += duration_us

            if req.priority == Priority.CRITICAL:
                total_critical += 1
                if req.deadline_us > 0.0 and req.completion_time_us <= req.deadline_us:
                    critical_satisfied += 1

        # Effective active busy times across 8 channels
        # (Since channels operate in parallel, active power is modeled per active operating state)
        active_read_sec = total_read_time_us / 1e6 / 8.0 # distributed across 8 channels
        active_write_sec = total_write_time_us / 1e6 / 8.0
        
        # Standby time is when controller is powered on but idle
        active_sec = min(benchmark_sec, active_read_sec + active_write_sec)
        standby_sec = max(0.0, benchmark_sec - active_sec)

        read_joules = active_read_sec * self.power_read_w
        write_joules = active_write_sec * self.power_write_w
        standby_joules = standby_sec * self.power_standby_w
        total_joules = read_joules + write_joules + standby_joules

        num_reqs = max(1, len(requests))
        total_mb = max(0.001, total_bytes / (1024 * 1024))

        energy_per_req_mj = (total_joules / num_reqs) * 1000.0
        energy_per_mb_mj = (total_joules / total_mb) * 1000.0
        
        satisfied_divisor = max(1, critical_satisfied)
        energy_per_satisfied_mj = (total_joules / satisfied_divisor) * 1000.0

        return EnergyProfile(
            total_energy_joules=round(total_joules, 4),
            active_read_joules=round(read_joules, 4),
            active_write_joules=round(write_joules, 4),
            idle_standby_joules=round(standby_joules, 4),
            energy_per_request_mj=round(energy_per_req_mj, 3),
            energy_per_mb_mj=round(energy_per_mb_mj, 3),
            energy_per_satisfied_critical_req_mj=round(energy_per_satisfied_mj, 3),
            satisfied_critical_count=critical_satisfied,
            total_critical_count=total_critical
        )
