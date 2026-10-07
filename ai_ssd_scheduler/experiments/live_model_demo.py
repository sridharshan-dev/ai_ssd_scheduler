"""Run TEMPO with urgency metadata emitted by a live PyTorch model loop."""

import argparse
import time
from typing import List

import torch
from torch import nn

from ..runtime import LiveModelTelemetry, RuntimePhase
from ..schedulers.ai_ssd import AIAndSSDStateScheduler
from ..ssd.request import Request
from ..ssd.simulator import Simulator


class TinyDecoder(nn.Module):
    """Small CPU model used only to exercise runtime callbacks."""

    def __init__(self, vocab_size: int = 128, hidden_size: int = 32):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, hidden_size)
        self.projection = nn.Linear(hidden_size, vocab_size)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        return self.projection(self.embedding(tokens).mean(dim=1))


def monotonic_us(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1000.0


def make_request(request_id: int, now_us: float, is_write: bool, sector: int) -> Request:
    return Request(
        req_id=request_id,
        arrival_time_us=now_us,
        op="W" if is_write else "R",
        size_bytes=131072,
        start_sector=sector,
        num_sectors=256,
    )


def run_demo(decode_steps: int = 8) -> List[Request]:
    torch.manual_seed(7)
    model = TinyDecoder().eval()
    telemetry = LiveModelTelemetry(token_sla_us=800.0)
    requests: List[Request] = []
    start_ns = time.perf_counter_ns()
    request_id = 0

    with torch.inference_mode():
        telemetry.set_phase(RuntimePhase.PREFILL, monotonic_us(start_ns))
        model(torch.randint(0, 128, (1, 16)))
        requests.append(make_request(request_id, monotonic_us(start_ns), False, 0))
        telemetry.annotate_io(requests[-1], requests[-1].arrival_time_us)
        request_id += 1

        for step in range(decode_steps):
            now_us = monotonic_us(start_ns)
            token_deadline = now_us + telemetry.token_sla_us
            telemetry.set_phase(
                RuntimePhase.DECODE,
                now_us,
                next_token_deadline_us=token_deadline,
            )
            model(torch.randint(0, 128, (1, 1)))
            request = make_request(request_id, monotonic_us(start_ns), False, 256 + step * 256)
            telemetry.annotate_io(request, request.arrival_time_us)
            requests.append(request)
            request_id += 1

        checkpoint_time = monotonic_us(start_ns)
        telemetry.set_phase(RuntimePhase.CHECKPOINT, checkpoint_time)
        checkpoint = make_request(request_id, checkpoint_time, True, 100000000)
        telemetry.annotate_io(checkpoint, checkpoint_time)
        requests.append(checkpoint)
        request_id += 1

        sync_time = monotonic_us(start_ns)
        telemetry.set_phase(RuntimePhase.SYNC, sync_time)
        sync_request = make_request(request_id, sync_time, False, 2048)
        telemetry.annotate_io(sync_request, sync_time)
        requests.append(sync_request)

    simulator = Simulator(max_in_flight=8, phase_aware_gc=True)
    simulator.run(requests, AIAndSSDStateScheduler())
    print("Live PyTorch runtime metadata:")
    for request in requests:
        print(
            f"  req={request.req_id:02d} class={request.data_class:<22} "
            f"priority={request.priority.name:<10} "
            f"deadline={request.deadline_us - request.arrival_time_us:7.1f} us"
        )
    print(f"Placement pools: {simulator.backend.pool_page_counts}")
    return requests


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decode-steps", type=int, default=8)
    args = parser.parse_args()
    run_demo(args.decode_steps)


if __name__ == "__main__":
    main()
