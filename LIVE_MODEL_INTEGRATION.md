# Live Model Urgency Integration

The runtime adapter is in `ai_ssd_scheduler/runtime/live_model.py`.
It converts model-runtime events into the existing TEMPO request fields:

- `request.priority`
- `request.deadline_us`
- `request.data_class`

## Run the local PyTorch proof

PyTorch is used here as a real model-runtime source, with a small CPU decoder:

```powershell
python -m ai_ssd_scheduler.experiments.live_model_demo --decode-steps 4
```

This executes prefill and decode inference, then emits checkpoint and sync
events. The resulting requests are passed through the TEMPO simulator and the
assigned priorities, deadlines, classes, and placement pools are printed.

## Minimal integration

```python
from ai_ssd_scheduler.runtime import LiveModelTelemetry, RuntimePhase

telemetry = LiveModelTelemetry(token_sla_us=800.0)

# Call this from the model runtime when a phase changes.
telemetry.set_phase(RuntimePhase.DECODE, now_us=runtime_time_us)

# Call this immediately before submitting an I/O request.
request = telemetry.annotate_io(request, now_us=runtime_time_us)
submit_to_storage(request)
```

For a token deadline supplied by the serving system, pass an absolute deadline:

```python
telemetry.set_phase(
    RuntimePhase.DECODE,
    now_us=runtime_time_us,
    next_token_deadline_us=request_deadline_us,
)
```

## Runtime event mapping

| Runtime event | TEMPO behavior |
|---|---|
| `DECODE` | Read requests become `CRITICAL`; class becomes `KV_CACHE` |
| `PREFILL` | Reads become `NORMAL`; class becomes `MODEL_WEIGHTS` |
| `CHECKPOINT` | Writes become `BACKGROUND`; class becomes `OPTIMIZER_CHECKPOINT` |
| `SYNC` | Requests become `CRITICAL` with a short relative deadline |
| `IDLE` | Requests become `BACKGROUND` with a loose deadline |

## PyTorch/vLLM connection

The adapter is framework-neutral. Connect it to the runtime callback that knows the
current phase and SLA. For a prototype, the callback can be placed around the
batch/decode loop:

```python
telemetry.set_phase(RuntimePhase.DECODE, monotonic_us())
for io_request in pending_storage_requests:
    telemetry.annotate_io(io_request, monotonic_us())
```

For training, use the equivalent hooks around checkpoint save and distributed
synchronization. The important boundary is that the runtime supplies phase/SLA
telemetry; TEMPO does not claim to recover an exact deadline from raw block I/O.

## Evaluation modes

Keep two experiment modes:

1. **Oracle mode:** existing controlled annotations, useful for measuring the upper bound.
2. **Live-runtime mode:** this adapter supplies priority and deadlines from model events.

Compare both against raw-I/O inference to quantify the cost of imperfect metadata.
