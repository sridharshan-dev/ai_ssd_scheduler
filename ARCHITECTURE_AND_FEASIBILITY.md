# Project TEMPO: Architecture, Overhead, Energy, and Feasibility Analysis
*Phases 10 through 14: System Mechanics, Complexity, Energy Modeling, and Controller Implementation*

---

## 1. Phase 10: Scheduler Overhead & Algorithmic Complexity

A critical concern in host-storage co-design is dispatch overhead:
> *"TEMPO shouldn't get credit for saving 100 µs if it takes 200 µs to make its decision."*

### 1.1 Algorithmic Complexity Derivation
Let:
- $Q$ = Current number of candidate requests pending in the scheduler queue ($0 \le Q \le \text{Queue Depth}$).
- $P$ = Number of physical flash sub-pages per request ($P = \lceil \text{Size} / \text{Page\_Size} \rceil$). For the dominant 128 KiB KV-cache transfer on a 32 KiB page architecture, $P = 4$.
- $C$ = Number of flash channels ($C = 8$).

For each candidate request $r \in Q$:
1. **AI Urgency Calculation:**
   $$\text{Score}_{\text{AI}} = (\text{Priority} \times W_{\text{urgency}}) + \frac{W_{\text{deadline}}}{\text{Deadline} - \text{Now} + 10}$$
   Cost: 1 subtraction, 1 division, 1 multiplication, 1 addition $\to \mathcal{O}(1)$.
2. **SSD State Delay Lookup:**
   For each sub-page $p \in P$:
   - Read `channel[p.channel_id].bus_busy_until` (1 SRAM 64-bit integer read) $\to \mathcal{O}(1)$.
   - Read `channel[p.channel_id].lun_busy_until[p.lun_id]` (1 SRAM 64-bit integer read) $\to \mathcal{O}(1)$.
   - Compute earliest pipeline readiness $\to \mathcal{O}(1)$.
   Cost: $2 \times P$ SRAM reads $\to \mathcal{O}(P)$.

**Total Decision Complexity:**
$$\mathcal{O}(Q \times P)$$
Because $P \le 4$ and controller submission queues are bounded ($Q \le 32$), the candidate evaluation loop requires at most **128 iterations**.
**Space Complexity:** $\mathcal{O}(1)$ auxiliary memory (in-place evaluation using existing NVMe command descriptors in controller SRAM).

### 1.2 Empirical Microbenchmarking & Hardware Controller Projection

| Queue Depth ($QD$) | Avg Candidates Evaluated | Avg Hardware State Lookups | Python Measurement ($\mu\text{s}$) | Projected ARM Cortex-R8 Cycles | Projected Controller Execution Time ($\mu\text{s}$) | Overhead as % of NAND Read ($76.96\ \mu\text{s}$) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **1** | 1.0 | 8.0 | 2.1 | 103 cycles | **0.129 µs** | **0.17%** |
| **4** | 3.8 | 30.4 | 8.4 | 280 cycles | **0.350 µs** | **0.45%** |
| **8** | 7.5 | 60.0 | 16.2 | 512 cycles | **0.640 µs** | **0.83%** |
| **16** | 14.8 | 118.4 | 31.5 | 972 cycles | **1.215 µs** | **1.58%** |
| **32** | 28.2 | 225.6 | 58.7 | 1,816 cycles | **2.270 µs** | **2.95%** |

*Hardware Execution Model: Enterprise NVMe controller equipped with dual ARM Cortex-R8 cores clocked at 800 MHz (1.25 ns/cycle), executing compiled C firmware with single-cycle SRAM access.*

### Takeaway:
At typical NVMe operational queue depths ($QD=8\text{–}16$), TEMPO takes **0.64 µs to 1.21 µs** on an embedded ARM controller core. Compared to the physical $76.96\ \mu\text{s}$ service time of a 128 KiB NAND page transfer ($36\ \mu\text{s}$ sensing + $41\ \mu\text{s}$ bus transfer), TEMPO consumes **less than 1.6% of the I/O service budget**, making it exceptionally lightweight for real-time firmware execution.

---

## 2. Phase 11: Defensible SSD Energy Model

Rather than claiming "TEMPO reduces raw drive power," we grounded our analysis in published Samsung 970 Pro specifications to investigate the systems metric: **Energy per Deadline-Satisfied AI Request**.

### 2.1 Power Parameters (Samsung 970 Pro Grounding)
- **Active Read Power ($P_{\text{read}}$):** $5.2\ \text{W}$
- **Active Write Power ($P_{\text{write}}$):** $5.7\ \text{W}$
- **Active Controller Standby Power ($P_{\text{standby}}$):** $0.5\ \text{W}$
- **Low-Power Idle ($P_{\text{idle}}$, L1.2 state):** $0.03\ \text{W}$

### 2.2 Empirical Energy Results (1,500 CHEOPS Requests, Slack = 800 µs, BG = 200 IOPS)

| Scheduler Policy | Total Energy (Joules) | Energy / Request (mJ) | Energy / MB (mJ / MB) | Critical Deadlines Met | Deadline Miss % | **Energy / Satisfied AI Req (mJ)** |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **`S0-FIFO`** | 0.6145 J | 0.408 mJ | 3.290 mJ | 80 / 596 | 86.6% | 7.682 mJ |
| **`S1-AI-Priority`** | 0.6101 J | 0.405 mJ | 3.266 mJ | 422 / 596 | 29.2% | 1.446 mJ |
| **`S2-SSD-State`** | 0.5964 J | 0.396 mJ | 3.193 mJ | 94 / 596 | 84.2% | 6.345 mJ |
| **`S3-TEMPO`** | **0.6051 J** | **0.402 mJ** | **3.240 mJ** | **561 / 596** | **5.9%** | **1.079 mJ** |

```
Energy Consumed Per Deadline-Satisfied AI Request (Lower is Better)
S0-FIFO:         ████████████████████████████████████ 7.682 mJ
S2-SSD-State:    █████████████████████████████ 6.345 mJ
S1-AI-Priority:  ███████ 1.446 mJ
S3-TEMPO:        █████ 1.079 mJ   (25.4% lower energy per useful output!)
```

### 2.3 Research Finding:
1. **Total Drive Energy is Invariant:** Total electrical energy consumed is virtually identical across all schedulers (~0.60 J to 0.61 J). This makes physical sense: moving 187 MB of flash data requires charging the same number of NAND bitlines and transferring the same bytes across the PCIe bus.
2. **The "Wasted Energy" Discovery:** Under `S1-AI-Priority`, 174 critical requests miss their host deadline. The SSD still expends electrical energy reading and transferring those 174 blocks, but because they arrive too late, they trigger pipeline stalls in the host LLM runtime.
3. **Productive Efficiency:** By completing 561 out of 596 critical requests on time, **TEMPO achieves a 25.4% reduction in Energy per Deadline-Satisfied Request** ($1.079\ \text{mJ}$ vs. $1.446\ \text{mJ}$).

---

## 3. Phase 12: Architectural Scope — Decision on CSD

### The Question:
*Should Computational Storage Drives (CSD) / in-storage compute be included in Project TEMPO?*

### Formal Architectural Position: **NO — Scope CSD as an Orthogonal Future Extension.**

### Rationale:
1. **Preserves Clear Host-Storage Co-Design Semantics:**
   TEMPO's core contribution is:
   $$\text{AI Runtime Urgency Hint} \longrightarrow \text{NVMe Ingress} \longrightarrow \text{State-Aware Dispatch} \longrightarrow \text{NAND Physical Channels}$$
   This solves the fundamental I/O scheduling bottleneck without altering the storage programming model.
2. **Avoids Confounding Variables:**
   Adding in-drive computation (e.g. running attention kernels or GEMMs on FPGA/RISC-V inside the drive) fundamentally alters memory coherence, offload programming models, host-device bandwidth ratios, and thermal envelopes. It obscures whether performance gains stem from scheduling or compute offloading.
3. **Near-Term Commercial Deployability:**
   TEMPO requires **zero new hardware silicon**. It runs as a firmware update to existing enterprise SSD controllers and uses standard NVMe command Dwords. In contrast, CSD requires non-standard silicon, specialized software toolchains, and proprietary host APIs.
4. **Future Roadmap ("TEMPO-CSD"):**
   CSD can be introduced as a downstream extension where in-drive compute kernels register their own internal deadlines with TEMPO's flash dispatcher.

---

## 4. Phase 13: Implementation Feasibility & NVMe Protocol Mapping

Where does TEMPO actually live, and how do hints cross the host/controller boundary?

### 4.1 Host-to-Controller Interface (NVMe Protocol Mapping)
TEMPO requires no custom PCIe hardware. Urgency hints are conveyed via standard NVMe 2.0 command submission primitives:

```
                  Standard NVMe 64-Byte Command Entry
┌────────────────────────────────────────┬────────────────────────────────────────┐
│ Dword 0: Opcode (0x02 Read, 0x01 Write)│ Dword 1: Namespace ID (NSID)           │
├────────────────────────────────────────┼────────────────────────────────────────┤
│ Dwords 2-9: Metadata Pointer & PRPs    │ Dwords 10-11: Starting LBA             │
├────────────────────────────────────────┼────────────────────────────────────────┤
│ Dword 12: Number of Logical Blocks     │ Dword 13: TEMPO AI Telemetry Extension │
└────────────────────────────────────────┴────────────────────────────────────────┘
```

#### Dword 13 Bit Allocation:
- **Bits [31:28] (4 bits) — AI Priority Class:**
  - `0001b` = Background (Prefetch, checkpoints, logs)
  - `0010b` = Normal (Standard model weights, context tokens)
  - `0011b` = Critical (Next-token generation KV-cache blocks)
- **Bits [27:12] (16 bits) — Relative Deadline Slack ($\Delta t_{\text{slack}}$):**
  - Encodes deadline slack in units of $10\ \mu\text{s}$ ($0\text{–}655,350\ \mu\text{s}$).
  - Example: A $800\ \mu\text{s}$ deadline is encoded as integer value `80`.
- **Bits [11:0] (12 bits) — Stream / Tenant Tag:**
  - Identifies distinct LLM inference streams for multi-tenant fairness.

*Alternative Standard Interface:* NVMe **Directive Send / Receive** or **Flexible Data Placement (FDP)** stream placement handles can also carry this tag without modifying standard read/write Dwords.

### 4.2 Firmware Architecture Inside the SSD Controller

```
                               HOST CPU / GPU
                       PyTorch / vLLM KV-Cache Offload
                                     │
                                     │ NVMe Read with Dword 13 Hints
                                     ▼
                       PCIE / NVMe FRONTEND (ASIC)
                                     │
                                     │ DMA Submission Queue (SQ)
                                     ▼
                      TEMPO FIRMWARE DISPATCHER
                    (Embedded ARM Cortex-R8 Core)
                 ┌──────────────────────────────────────┐
                 │ 1. Decode Priority & Deadline        │
                 │ 2. Query FTL Physical LBA Mapping    │
                 │ 3. Read Channel Bus Busy Timers      │
                 │ 4. Read LUN Sense/Prog Status        │
                 │ 5. Compute TEMPO Urgency Score       │
                 └──────────────────┬───────────────────┘
                                    │
                        Dispatches Optimal Request
                                    ▼
                      FLASH CHANNEL SEQUENCERS
           ┌──────────┬──────────┬──────────┬──────────┐
           │ Channel 0│ Channel 1│   ...    │ Channel 7│
           └──────────┴──────────┴──────────┴──────────┘
```

1. **FTL Integration:** The FTL translates the requested LBA to physical `(Channel, LUN, Block, Page)`.
2. **Channel Hardware Query:** The dispatcher inspects internal hardware register timers in controller SRAM (`bus_busy_until`, `lun_busy_until`).
3. **Dispatch Commit:** Instead of popping commands in FIFO queue order, the dispatcher executes `select_next()` and programs the target channel DMA engine.

---

## 5. Phase 14: Hardware Prototype & Controller Emulation Architecture

To evaluate TEMPO without requiring proprietary vendor-locked firmware signing keys:

### 5.1 Three-Tier Validation Methodology
1. **Tier 1 — Cycle-Accurate Simulator (`ai_ssd_scheduler/`):**
   - High-throughput exploration across 9 contention levels, 14 deadline points, 10 random seeds, and parameter perturbations.
2. **Tier 2 — Native C Controller Firmware Prototype (`tempo_controller/`):**
   - Implemented in ISO C99, compiled with `gcc -O2`.
   - Ingests real host CHEOPS traces, encapsulates commands into standard 64-byte NVMe Submission Queue Entries (SQEs), and executes cycle-accurate channel dispatching.
   - **Live Results:** S0-FIFO achieves 85.04% misses; S1-AI-Priority achieves 30.19% misses; S3-TEMPO cuts misses down to **10.19%** (a **20.00 percentage point reduction**) and slashes P95 latency from 1,472.4 µs to **1,123.5 µs** (a **348.8 µs win**).
3. **Tier 3 — NVMeVirt Linux Kernel Integration (`tempo_controller/nvmevirt_patch/nvmevirt_tempo.c`):**
   - Implements a drop-in C hook into NVMeVirt's kernel module request arbitration path (`nvmev_arbitrate()`).
   - Hooks into the NVMe target driver to perform hardware-state and urgency-aware arbitration in Linux kernel space.

See [CONTROLLER_PROTOTYPE_REPORT.md](file:///d:/Projects/Sandisk/CONTROLLER_PROTOTYPE_REPORT.md) for full prototype implementation details, source code, and benchmark logs.
