# Project TEMPO

### An SSD that knows *what* the data is and *when* the GPU needs it

**Track:** Designing the SSD for the AI Era
**Category:** Firmware / FTL architecture (simulation + live prototype)
**Submitted to:** SanDisk Hackathon

---

## 1. The One-Paragraph Pitch

Today's SSD firmware sees an AI training job as an anonymous stream of block addresses. It cannot tell a permanent model weight from a KV-cache entry that dies in two seconds, and it has no idea whether the GPU is mid-computation or idle. Because of that blindness, it mixes data with wildly different lifetimes into the same erase block (driving write amplification past 3.5×) and fires garbage collection at the exact moment a distributed training cluster is waiting at a synchronization barrier (stalling every GPU in the cluster, not just one).

**Project TEMPO adds two small pieces of intelligence to SSD firmware: a classifier that infers *what kind* of AI data each write is, and a phase detector that infers *what the GPU is doing right now*. It then uses both to decide where data physically lands and when background work is allowed to run.** No new NAND. No new silicon. No changes required to PyTorch. Just firmware that pays attention.

---

## 2. The Problem, in Plain Terms

Picture a warehouse worker who receives unlabeled boxes and shelves them in arrival order. Some boxes hold items thrown out in an hour; others hold items kept for years. Because nothing is labeled, every shelf ends up half-empty and half-permanent, and clearing space means constantly shuffling boxes around. Worse, the worker reorganizes shelves at random times — including the exact moment the loading dock needs everything to move fast.

That is a conventional FTL handling an AI workload.

Three concrete consequences, straight from the engineering analysis:

| What goes wrong | Measured effect |
|---|---|
| Weights, optimizer states, and KV-cache spills share erase blocks | WAF climbs from an ideal ~1.05 to **3.5–5.0×** — burning write bandwidth and NAND endurance |
| GC fires during a synchronous collective (`AllReduce`) | A single **10 ms** pause on one drive idles the **entire multi-node cluster** |
| Checkpoint burst saturates volatile buffers | Writes collapse to raw NAND program speed (tPROG ≈ 600–2,400 µs), stalling the forward pass |

The unifying cause is not NAND being slow. It is that **the firmware has no model of the workload it is serving.**

---

## 3. The Idea: Two Engines

TEMPO is two lightweight firmware engines feeding one placement-and-scheduling policy.

### Engine 1 — The Semantic Classifier ("What is this?")

Watches the I/O stream and infers a data class from its signature alone — no host cooperation needed.

| Class | Telltale signature | Where TEMPO puts it |
|---|---|---|
| **Model weights** | Huge, sequential, written once, read forever | Isolated QLC blocks, never GC'd with anything else |
| **Optimizer / checkpoint state** | Large, strictly periodic, fully overwritten each cycle | Multi-channel striped blocks, whole-block invalidation |
| **KV-cache / activations** | Small, unaligned, overwritten within seconds | Fast pSLC pool, dies as a unit — near-zero GC cost |
| **Training samples** | Read-heavy, shuffled, never written | Read-optimized, excluded from write paths entirely |

The point: **data with the same lifetime lives together, so blocks die whole.** No valid-page copying, no fragmentation, no compaction storm.

### Engine 2 — The Phase Detector ("What is the GPU doing?")

AI training has a heartbeat. Data loading, forward pass, backward pass, checkpoint, synchronization barrier, idle — each has a distinct I/O fingerprint, and the pattern repeats every step. TEMPO learns that rhythm and predicts the next phase *before it arrives*.

```
   Detected phase          TEMPO's decision
   ─────────────────────────────────────────────────
   Data loading      →     prefetch aggressively, GC paused
   Forward/backward  →     I/O quiet — run GC hard, now
   Checkpoint burst  →     route to pSLC, freeze all background work
   Sync barrier      →     absolute latency protection, zero maintenance
   Idle              →     fold pSLC back to QLC, scrub, wear-level
```

**This is the part nobody else is doing.** The NVMe standard has a mechanism for *placement* hints (Flexible Data Placement). It has **no mechanism at all** for communicating *execution phase*. TEMPO infers it.

### Why the combination matters

Knowing a write is an optimizer state tells you nothing about whether the GPU is idle. Knowing the GPU is idle tells you nothing about where the data should go. Placement is a **spatial** decision; scheduling is a **temporal** one. Solve only one and you leave half the win on the table.

---

## 4. Why This Idea Ranks First

We evaluated five candidate directions against four hackathon-critical criteria.

| # | Candidate idea | Firmware-only? | Buildable in hackathon? | Already solved? | Demo impact | **Verdict** |
|---|---|---|---|---|---|---|
| **1** | **TEMPO (semantic + phase-aware FTL)** | ✅ Yes | ✅ Simulator + live detector | ❌ No | ⭐⭐⭐⭐⭐ | **SELECTED** |
| 2 | In-storage vector search for RAG | ❌ Needs new silicon | ⚠️ Emulation only | ❌ No | ⭐⭐⭐⭐ | Stretch goal |
| 3 | On-drive decompression / tokenization | ❌ Needs new silicon | ⚠️ Emulation only | ❌ No | ⭐⭐⭐ | Stage two |
| 4 | Direct SSD→GPU DMA path | ✅ Yes | ✅ Yes | ⚠️ **GPUDirect Storage ships today** | ⭐⭐ | Rejected — inherit as baseline |
| 5 | SSD-backed KV-cache offload | ✅ Yes | ✅ Yes | ❌ No | ⭐ | Rejected — 1,000× latency gap vs HBM makes it unviable for live decoding |

**TEMPO is the only candidate that is simultaneously pure firmware, genuinely unsolved, and fully demonstrable without fabricating hardware.**

### The honesty that makes it credible

A weaker proposal would say "let the host tag its writes with lifetime hints." That is *already an NVMe standard* — proposing it is proposing something that exists. TEMPO's actual contribution sits one layer above:

> **Inferring the class and the phase when the host tells you nothing at all** — then coordinating placement, GC, and cache admission from those inferences.

That works on unmodified PyTorch, on drives already in the field, and on customers who will never change their training code.

---

## 5. Architecture

```
        Unmodified PyTorch / DeepSpeed training job
                          │
                          │  (plain NVMe reads & writes — no hints)
                          ▼
        ┌─────────────────────────────────────────────┐
        │              TEMPO FIRMWARE                 │
        │                                             │
        │   ┌──────────────┐    ┌──────────────────┐  │
        │   │  SEMANTIC    │    │  PHASE DETECTOR  │  │
        │   │  CLASSIFIER  │    │                  │  │
        │   │  "what is    │    │  "what is the    │  │
        │   │   this?"     │    │   GPU doing?"    │  │
        │   └──────┬───────┘    └────────┬─────────┘  │
        │          │                     │            │
        │          └──────────┬──────────┘            │
        │                     ▼                       │
        │         ┌───────────────────────┐           │
        │         │   POLICY ENGINE       │           │
        │         │  · where data lands   │           │
        │         │  · when GC may run    │           │
        │         │  · what gets cached   │           │
        │         │  · pSLC pool sizing   │           │
        │         └───────────┬───────────┘           │
        └─────────────────────┼───────────────────────┘
                              ▼
              ┌───────────────┴────────────────┐
              ▼               ▼                ▼
        pSLC POOL       STRIPED QLC       ISOLATED QLC
        (KV cache,      (checkpoints,     (model weights,
         checkpoints)    optimizer)        read-only)
```

Three things to notice: the host is unmodified, the NAND is unmodified, and every box added is software.

---

## 6. Implementation Workflow

Structured for a 36-hour event. Adjust the clock, keep the order.

### Phase 0 — Setup *(Hours 0–3)*

- Stand up **MQSim** (trace-driven SSD simulator, C++) as the baseline FTL.
- Instrument a small real PyTorch training job (ResNet or a tiny transformer) with `blktrace` to capture genuine block I/O.
- Capture three traces: **normal training**, **training + periodic checkpointing**, **inference serving**.

**Deliverable:** real AI I/O traces + a working baseline simulator.

### Phase 1 — Ground Truth *(Hours 3–8)*

- Annotate the captured traces with true labels (this write *is* a checkpoint; this window *is* a backward pass) using PyTorch hooks and timestamps.
- This is the answer key. Without it you cannot prove the classifier works.

**Deliverable:** labeled dataset for training and validating both engines.

### Phase 2 — Semantic Classifier *(Hours 8–15)*

- Extract per-stream features: request size distribution, sequentiality, overwrite rate, inter-arrival periodicity, read/write ratio.
- Train a **decision tree or small random forest** — deliberately not a neural net. It must be explainable, tiny, and plausibly runnable on an Arm Cortex-R controller.
- Validate: classification accuracy per data class on held-out traces.

**Deliverable:** classifier hitting a target of **>90% accuracy**, with a printed decision tree you can show a judge.

### Phase 3 — Phase Detector *(Hours 15–22)*

- Detect the periodic training-step rhythm via autocorrelation on the I/O arrival series.
- Predict the next phase transition from the learned period.
- **Measure detection lead time** — the single most important number in the project. Deferring GC only helps if you predict the barrier *before* it arrives. A checkpoint detected 200 ms late has already stalled the cluster.

**Deliverable:** phase detector with a stated lead time in milliseconds.

> ⚠️ **Critical checkpoint.** If lead time is too short to be useful, drop the temporal half and ship placement-only. Test this early so the fallback is a decision, not a scramble.

### Phase 4 — Policy Engine into the FTL *(Hours 22–30)*

- Modify MQSim's FTL: route writes to separate block pools by predicted class.
- Add a GC gate driven by predicted phase.
- Add pSLC absorption for detected checkpoint bursts, with folding during detected idle.

**Deliverable:** TEMPO FTL running the same traces as the baseline.

### Phase 5 — Results and Demo *(Hours 30–36)*

- Run the progressive comparison: **Baseline → +Semantic Placement → +Phase-Aware GC → Full TEMPO**. Progressive layering shows exactly which mechanism earns which gain.
- Build the live demo (below).
- Prepare the pitch.

---

## 7. The Demo

Two screens, side by side, both running the same real trace.

**Left — Baseline SSD.** A block-layout visualizer showing weights, optimizer state, and KV data interleaved into shared blocks; GC events firing on top of read spikes; a latency graph with visible tail spikes.

**Right — TEMPO.** The same trace. Clean color-separated block pools. A live phase readout scrolling `DATA_LOAD → FORWARD → BACKWARD → CHECKPOINT → SYNC → IDLE`. GC events clustered visibly inside idle windows only. A flat latency graph.

**The moment that sells it:** point at the screen as the phase detector correctly calls `CHECKPOINT` *a beat before the write burst arrives*, and GC visibly stands down.

---

## 8. What We Measure

| Metric | Baseline | TEMPO target | How measured |
|---|---|---|---|
| **Write Amplification Factor** | 3.5–5.0× | **< 1.5×** | NAND writes ÷ host writes, from simulator counters |
| **P99.9 read latency** | Spiky | **50%+ reduction** | Latency histogram across full trace |
| **GC events during critical phases** | Uncontrolled | **≈ 0** | Cross-reference GC log with phase ground truth |
| **Checkpoint stall time** | Full burst duration | **60%+ reduction** | Time-to-completion for checkpoint writes |
| **Classifier accuracy** | n/a | **> 90%** | Predicted vs. labeled ground truth |
| **Phase detection lead time** | n/a | **Report honestly** | Predicted transition vs. actual, in ms |
| **NAND endurance** | Baseline P/E | **Proportional to WAF gain** | Total program/erase cycles consumed |

Reporting lead time honestly — even if it disappoints — is a strength. Judges trust a team that names its own weak parameter.

---

## 9. Scope Boundaries — What We Explicitly Do Not Claim

This section exists on purpose. It is what separates a proposal a reviewer trusts from a wish list.

**We do not claim:**

- ❌ That firmware can close the **30–100× bandwidth gap** between NAND and HBM. It cannot. Physics.
- ❌ That we improve **SSD→GPU transfer** — GPUDirect Storage already ships and solves it. We inherit it as a baseline.
- ❌ That we fix **cluster metadata, network fabric, or multi-tenant** bottlenecks. Those are distributed-systems problems above the drive boundary.
- ❌ That SSDs can serve **live KV-cache decoding**. A 40–100 µs flash read against sub-microsecond HBM is a 1,000× gap.
- ❌ That we eliminate **garbage collection**. Erase-before-write is architectural. We reschedule it; we do not remove it.

**We do claim:** firmware that infers workload semantics and execution phase can materially reduce write amplification, checkpoint stalls, and tail latency — with no new silicon, no new standards, and no host code changes.

---

## 10. Stretch Goals

If the core lands early:

1. **Near-data filtering hook** — a fixed-function decompression stub in the simulated data path, quantifying PCIe bytes saved.
2. **Multi-tenant fairness** — two simulated jobs sharing one drive, with per-tenant phase awareness preventing noisy-neighbor collisions.
3. **NVMe FDP bridge** — when the host *does* emit FDP directives, use them; fall back to inference when it does not. Best of both, and directly aligned with where the standard is heading.

---

## 11. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase detection lead time too short | Medium | Tested at Hour 22 by design; fall back to placement-only, which stands alone |
| Classifier overfits to one model architecture | Medium | Capture traces from two different model types in Phase 0 |
| MQSim modification proves too slow | Low | Fallback: lightweight custom Python trace replayer — less realistic, still shows the delta |
| Judges see it as "just FDP" | **High** | Lead the pitch with the inference contribution and the phase dimension FDP has no answer for |

That last risk is the one that decides the outcome. Address it in the first thirty seconds of the pitch, not the last.

---

## 12. Why SanDisk

This is a firmware and controller-architecture contribution that lands squarely inside SanDisk's domain — it makes existing NAND and existing controllers behave better for the fastest-growing storage workload in the market. It requires no fab change, no new interface, and no customer code change. It is the kind of intelligence that ships in a firmware revision.

The one-line version:

> **Stop building SSDs that only understand addresses. Build one that understands the job.**
