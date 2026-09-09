"""Parser for published CHEOPS'25 bpftrace block I/O traces."""

import os
from typing import List, Optional
from ..ssd.request import Request

class CheopsTraceParser:
    """Parses real bpftrace CSV outputs from CHEOPS'25 artifact repository."""

    @staticmethod
    def parse_line(line: str) -> Optional[tuple]:
        """
        Parses a single line:
        <timestamp_ns>, <op>, <size_bytes>, <start_sector>, <num_sectors>
        """
        line = line.strip()
        if not line or not line[0].isdigit():
            return None
            
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 5:
            return None
            
        try:
            ts_ns = int(parts[0])
            op = parts[1]
            size_bytes = int(parts[2])
            start_sector = int(parts[3])
            num_sectors = int(parts[4])
            return ts_ns, op, size_bytes, start_sector, num_sectors
        except (ValueError, IndexError):
            return None

    @classmethod
    def load_requests(
        cls,
        trace_path: str,
        max_requests: Optional[int] = 10000,
        skip_initial: int = 0
    ) -> List[Request]:
        """
        Loads and parses requests from the trace file.
        Sorts by timestamp (re-ordering any multi-core probe logging jitter)
        and normalizes timestamps strictly relative to the minimum timestamp (0.0 us).
        """
        if not os.path.exists(trace_path):
            raise FileNotFoundError(f"Trace file not found: {trace_path}")
            
        raw_entries = []
        skipped = 0

        with open(trace_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                parsed = cls.parse_line(line)
                if parsed is None:
                    continue
                    
                if skipped < skip_initial:
                    skipped += 1
                    continue
                    
                raw_entries.append(parsed)
                if max_requests is not None and len(raw_entries) >= max_requests:
                    break

        if not raw_entries:
            return []

        # Multi-core bpftrace probes can log events with slight microsecond out-of-order jitter.
        # Sort by timestamp to enforce physical arrival ordering:
        raw_entries.sort(key=lambda x: x[0])
        min_ts_ns = raw_entries[0][0]

        requests: List[Request] = []
        for req_id, (ts_ns, op, size_bytes, start_sector, num_sectors) in enumerate(raw_entries):
            arrival_time_us = (ts_ns - min_ts_ns) / 1000.0
            req = Request(
                req_id=req_id,
                arrival_time_us=arrival_time_us,
                op=op,
                size_bytes=size_bytes,
                start_sector=start_sector,
                num_sectors=num_sectors
            )
            requests.append(req)
                    
        return requests
