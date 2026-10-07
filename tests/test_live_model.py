import unittest

from ai_ssd_scheduler.runtime import LiveModelTelemetry, RuntimePhase
from ai_ssd_scheduler.schedulers.ai_ssd import AIAndSSDStateScheduler
from ai_ssd_scheduler.ssd.request import Priority, Request
from ai_ssd_scheduler.ssd.simulator import Simulator


class LiveModelTelemetryTests(unittest.TestCase):
    def make_request(self, op="R"):
        return Request(
            req_id=1,
            arrival_time_us=100.0,
            op=op,
            size_bytes=131072,
            start_sector=0,
            num_sectors=256,
        )

    def test_decode_uses_live_token_deadline(self):
        telemetry = LiveModelTelemetry(token_sla_us=800.0)
        telemetry.set_phase(RuntimePhase.DECODE, 100.0)
        request = telemetry.annotate_io(self.make_request(), 120.0)

        self.assertEqual(request.priority, Priority.CRITICAL)
        self.assertEqual(request.data_class, "KV_CACHE")
        self.assertEqual(request.deadline_us, 920.0)

    def test_checkpoint_write_is_background(self):
        telemetry = LiveModelTelemetry()
        telemetry.set_phase(RuntimePhase.CHECKPOINT, 100.0)
        request = telemetry.annotate_io(self.make_request("W"), 150.0)

        self.assertEqual(request.priority, Priority.BACKGROUND)
        self.assertEqual(request.data_class, "OPTIMIZER_CHECKPOINT")
        self.assertEqual(request.deadline_us, 100150.0)

    def test_sync_uses_tight_deadline(self):
        telemetry = LiveModelTelemetry(token_sla_us=800.0)
        telemetry.set_phase(RuntimePhase.SYNC, 100.0)
        request = telemetry.annotate_io(self.make_request(), 150.0)

        self.assertEqual(request.priority, Priority.CRITICAL)
        self.assertEqual(request.deadline_us, 400.0)

    def test_annotated_requests_reach_tempo_simulator(self):
        telemetry = LiveModelTelemetry()
        telemetry.set_phase(RuntimePhase.DECODE, 0.0)
        requests = []
        for request_id in range(4):
            request = Request(
                req_id=request_id,
                arrival_time_us=float(request_id * 20),
                op="R",
                size_bytes=131072,
                start_sector=request_id * 256,
                num_sectors=256,
            )
            requests.append(telemetry.annotate_io(request, request.arrival_time_us))

        simulator = Simulator(max_in_flight=2)
        result = simulator.run(requests, AIAndSSDStateScheduler())

        self.assertEqual(result.total_requests, 4)
        self.assertEqual(result.critical_requests, 4)
        self.assertGreater(simulator.backend.pool_page_counts["PSLC_HOT"], 0)


if __name__ == "__main__":
    unittest.main()
