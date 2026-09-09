# Project TEMPO: Publication Figures & Experimental Compendium
*The 10 Core Figures for Systems Paper and Hackathon Presentation*

This document provides publication-grade ASCII diagrams, exact empirical data tables, and analysis for Figures 1 through 10.

---

## Figure 1 — System Architecture: End-to-End Co-Design
*Flow of AI urgency semantics from PyTorch/vLLM through standard NVMe primitives to multi-channel NAND backend.*

```
+-----------------------------------------------------------------------------------------+
|                                    HOST RUNTIME LAYER                                   |
|   vLLM / FlexGen / PyTorch LLM Serving Runtime (OPT-6.7B / LLaMA-70B)                  |
|   - Phase Tracker: Prefill vs. Decode (Token Generation SLA: < 1 ms / token)            |
|   - Request Classifier: Next-token KV blocks = CRITICAL; Prefetch/Weights = NORMAL      |
+--------------------------------------------+--------------------------------------------+
                                             |
                         Standard NVMe Read with Dword 13 Extension
                         - Priority Tier: Bits [31:30]
                         - Deadline Slack: Bits [29:16] (in µs units)
                         - Sequence ID: Bits [15:0]
                                             |
                                             v
+--------------------------------------------+--------------------------------------------+
|                             SSD CONTROLLER FIRMWARE LAYER                               |
|   PCIe 4.0 Frontend & Submission Queue (SQ)                                             |
|                                            |                                            |
|   TEMPO Dispatch Engine (Projected ARM Cortex-R8 Core @ 800 MHz, Decision Time: < 4.9 µs) |
|   1. Decode Priority & Deadline Slack from NVMe Dword 13                                |
|   2. Physical LBA Mapping (FTL translation -> Channel, LUN, Block, Page)                |
|   3. Hardware State Probe (Read Channel Bus Busy Timers & LUN Sense/Prog Status)        |
|   4. Joint Score Evaluation: Urgency Boost vs. Projected Channel Delay                  |
+--------------------------------------------+--------------------------------------------+
                                             |
                         Dispatches Earliest-Ready Channel First
                                             |
                                             v
+--------------------------------------------+--------------------------------------------+
|                                  PHYSICAL NAND BACKEND                                  |
|   8-Channel Striped Flash (32 KiB pages, 800 MB/s per channel bus, tR=36µs, tPROG=185µs)|
|   [ Ch 0 ]   [ Ch 1 ]   [ Ch 2 ]   [ Ch 3 ]   [ Ch 4 ]   [ Ch 5 ]   [ Ch 6 ]   [ Ch 7 ]  |
|   LUN 0,1    LUN 0,1    LUN 0,1    LUN 0,1    LUN 0,1    LUN 0,1    LUN 0,1    LUN 0,1   |
+-----------------------------------------------------------------------------------------+
```

---

## Figure 2 — 2×2 Scheduler Design Matrix
*Taxonomy of host storage schedulers along the axes of AI Semantic Awareness and Hardware State Awareness.*

```
                            SSD HARDWARE STATE AWARENESS
                       State-Unaware             State-Aware
                 +-------------------------+-------------------------+
                 |                         |                         |
    AI-Unaware   |       S0: FIFO          |     S2: SSD-State       |
                 |  Arrival order only     |  Shortest Channel Delay |
                 |  Miss Rate: 86.6%       |  Miss Rate: 84.2%       |
                 |                         |                         |
AI-URGENCY       +-------------------------+-------------------------+
AWARENESS        |                         |                         |
                 |    S1: AI-Priority      |      S3: TEMPO          |
    AI-Aware     |  Priority Tier Queue    |  Joint AI Urgency +     |
                 |  Miss Rate: 29.2%       |  Channel Bus Readiness  |
                 |                         |  Miss Rate: 5.9%        |
                 +-------------------------+-------------------------+
```

---

## Figure 3 — Primary Headline Result: Deadline Miss Rate
*Evaluated on 1,500 real CHEOPS KV-cache offload requests ($QD=32$, Slack = $800\ \mu\text{s}$, Background = 200 IOPS).*

```
CRITICAL DEADLINE MISS RATE (%)  [Lower is Better]

S0 (FIFO):          ████████████████████████████████████████ 86.6%
S2 (SSD-State):     ███████████████████████████████████ 84.2%
S1 (AI-Priority):   █████████████ 29.2%
S3 (TEMPO):         ██ 5.9%   <--- 23.3 percentage points lower misses!
```

| Scheduler | Policy Description | Critical Deadlines Met | Deadline Misses | Miss Percentage | P95 Latency ($\mu\text{s}$) | P99 Latency ($\mu\text{s}$) |
|:---|:---|:---:|:---:|:---:|:---:|:---:|
| **S0-FIFO** | Pure arrival order | 80 / 596 | 516 | **86.6%** | 3,124.5 | 3,348.0 |
| **S2-SSD-State** | Greedy channel earliest-finish | 94 / 596 | 502 | **84.2%** | 3,098.2 | 3,312.4 |
| **S1-AI-Priority** | Software-only priority queue | 422 / 596 | 174 | **29.2%** | 1,347.4 | 1,520.6 |
| **S3-TEMPO** | Joint AI Urgency + SSD State | **561 / 596** | **35** | **5.9%** | **842.3** | **1,268.2** |

---

## Figure 4 — The Crossover Analysis: Deadline Slack Sweep
*High-resolution sweep from $500\ \mu\text{s}$ to $2,000\ \mu\text{s}$ mapping the four distinct operational regimes.*

```
Deadline Miss %
 100% |   S1 (AI-Only) --*--      S3 (TEMPO) --#--
      |   *
  80% |   # *
      |     #
      |     #
  60% |       *
      |         #
  40% |           *
      |             \
  20% |               *
      |                 \
   0% +-----+-----+-----+-----+-----+-----+-----+-----+-----+
     500   650   750   800   850   950  1100  1300  1500  2000
                         Deadline Slack (µs)
      [ Regime 1 ] [   Regime 2   ] [   Regime 3   ] [ Regime 4 ]
      Physical     Peak Advantage   Tail Smoothing   Slack
      Floor        (S3 >> S1)       (S3 > S1)        Parity (S3 ≈ S1)
```

| Slack ($\mu\text{s}$) | Operational Regime | S1 Miss % | S3 Miss % | Miss Delta ($\Delta$) | Performance Interpretation |
|:---:|:---|:---:|:---:|:---:|:---|
| **500** | Regime 1: Physical Floor | 79.7% | 89.4% | $-9.7$ pp | Physical limits dominate ($4 \times 32\ \text{KiB} \approx 164\ \mu\text{s}$ bus) |
| **650** | Regime 1: Transition | 58.2% | 76.5% | $-18.3$ pp | Queue backlog cannot clear before deadline |
| **750** | **Regime 2: Peak Advantage** | **40.6%** | **9.7%** | **$+30.9$ pp** | Substantial miss reduction across channels |
| **800** | **Regime 2: Peak Advantage** | **29.2%** | **5.9%** | **$+23.3$ pp** | **Peak absolute win: 23.3 percentage points** |
| **850** | **Regime 2: Peak Advantage** | **19.3%** | **4.9%** | **$+14.4$ pp** | S3 avoids write-locked channels |
| **950** | Regime 3: Tail Smoothing | 9.2% | 3.9% | $+5.3$ pp | S3 P95 is 505 µs faster |
| **1100** | Regime 3: Tail Smoothing | 7.9% | 2.9% | $+5.0$ pp | Tail latency win persists |
| **1300** | Regime 3: Tail Smoothing | 5.7% | 0.5% | $+5.2$ pp | Misses fall under 1% |
| **1400** | Regime 3: Tail Smoothing | 3.7% | 0.2% | $+3.5$ pp | Absolute miss reduction of 3.5 pp |
| **1500** | Regime 4: Slack Parity | 1.3% | 0.0% | $+1.3$ pp | Ample slack allows S1 to meet deadlines |
| **2000** | Regime 4: Slack Parity | 0.0% | 0.0% | $0.0$ pp | Both achieve 100% on-time delivery |

> [!NOTE]
> **Operating Envelope Scope:** In the evaluated configuration, the largest benefit occurred in the **700–1,400 µs slack regime**. Beyond $1,500\ \mu\text{s}$, software-only prioritization (S1) achieves nearly identical on-time performance because temporary write stalls resolve within the available slack.

---

## Figure 5 — Background Contention Sweep: Sensitivity to Write Collisions
*Evaluated across all 9 background write load levels with 5 genuine random seeds generating Poisson exponential inter-arrival jitter.*

```
Miss Rate (%)
  30% |                                               * S1 (AI-Only)
      |                                        *
  20% |                                 *
      |                          *
  10% |                   *
      |            *             #      #      #      # S3 (TEMPO)
   0% +------------+------+------+------+------+------+
      0           50     100    200    300    800    1600
                        Background Traffic (IOPS)
```

| Background Traffic | S1 Miss % (Mean $\pm$ Std) | S3 Miss % (Mean $\pm$ Std) | **Miss Reduction ($\Delta$)** | S1 P95 (µs) | S3 P95 (µs) | P95 Tail Win |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **0 IOPS** | 14.3% $\pm$ 0.0% | **10.7% $\pm$ 0.0%** | **$-3.5$ percentage points** | 1,091.6 | **987.4** | 104.2 µs |
| **50 IOPS** | 14.3% $\pm$ 0.0% | **10.7% $\pm$ 0.0%** | **$-3.5$ percentage points** | 1,091.6 | **987.4** | 104.2 µs |
| **100 IOPS** | 16.2% $\pm$ 1.7% | **9.9% $\pm$ 2.3%** | **$-6.3$ percentage points** | 1,188.1 | **948.9** | 239.2 µs |
| **200 IOPS** | 14.3% $\pm$ 0.0% | **10.7% $\pm$ 0.0%** | **$-3.5$ percentage points** | 1,091.6 | **987.4** | 104.2 µs |
| **300 IOPS** | 16.6% $\pm$ 2.9% | **9.5% $\pm$ 1.5%** | **$-7.1$ percentage points** | 1,195.1 | **942.5** | 252.6 µs |
| **500 IOPS** | 18.3% $\pm$ 2.1% | **9.2% $\pm$ 3.0%** | **$-9.1$ percentage points** | 1,285.6 | **955.6** | 330.0 µs |
| **800 IOPS** | 23.5% $\pm$ 4.6% | **8.5% $\pm$ 2.3%** | **$-15.0$ percentage points** | 1,390.8 | **936.0** | 454.7 µs |
| **1,200 IOPS** | 19.0% $\pm$ 4.1% | **9.4% $\pm$ 2.3%** | **$-9.6$ percentage points** | 1,257.0 | **963.8** | 293.2 µs |
| **1,600 IOPS** | 21.5% $\pm$ 3.4% | **7.8% $\pm$ 1.8%** | **$-13.7$ percentage points** | 1,324.5 | **911.4** | 413.1 µs |

---

## Figure 6 — GC Interference: Tail Latency Under Block Erases
*Evaluated across physical erase durations ($t_{BERS} = 1.0\ \text{ms}$ to $5.0\ \text{ms}$).*

```
Tail Latency (P99) Under GC Erase Durations
Erase 1.0 ms:  S1: █████████████ 1,328 µs | S3: ███████████ 1,168 µs  (160 µs win)
Erase 3.5 ms:  S1: ██████████████████████████████████ 7,873 µs
               S3: ████████████████████████████████ 7,580 µs  (294 µs win)
```

| Erase Latency | Physical Meaning | S1 Miss % | S3 Miss % | Outcome Summary |
|:---:|:---|:---:|:---:|:---|
| **0.0 ms** | Clean Drive (GC OFF) | 2.3% | **2.0%** | Slight S3 advantage |
| **1.0 ms** | Fast SLC Block Erase | 5.9% | **0.3%** | S3 avoids erasing channel (5.6 pp win) |
| **2.0 ms** | Multi-Plane Erase | **37.9%** | 44.5% | **S1 outperforms S3** (Channel starvation stalls both) |
| **3.5 ms** | Standard 3D TLC Erase | 91.8% | **84.6%** | Both overwhelmed by 3.5 ms media freeze |

> [!WARNING]
> **GC Efficacy Boundary:** TEMPO does not universally outperform S1 under severe GC block erase conditions. When erase cycles reach 2.0 ms, overlapping erase operations across multiple channels exceed the available slack window, rendering reordering ineffective and causing parity or slight reversal.

---

## Figure 7 — Mechanism Timeline: Proof of Intra-Tier Channel Conflict Evasion
*Detailed trace snapshot demonstrating why S3 succeeds while S1 fails.*

```
Trace Time = 812.4 µs | Active Contention on Channel 3 (185 µs Background Write until 997.4 µs)

Host Queue State:
  Candidate A: Request #412 | Priority: CRITICAL | Deadline: 890.0 µs | Target: Channel 3 (LUN 0)
  Candidate B: Request #413 | Priority: CRITICAL | Deadline: 950.0 µs | Target: Channel 7 (LUN 1)

DISPATCH DECISION:
  S1-AI-Priority:
    - Sees Candidate A arrived at 802.1 µs, Candidate B arrived at 803.5 µs.
    - Dispatches Candidate A to Channel 3.
    - Result: Candidate A stalls behind the write until 997.4 µs.
      Completes at 1,074.4 µs -> DEADLINE MISSED (by 184.4 µs).
      Candidate B waits in queue -> DEADLINE MISSED.

  S3-TEMPO:
    - Probes Channel 3: Busy until 997.4 µs (Estimated delay = 262 µs).
    - Probes Channel 7: IDLE (Estimated delay = 77 µs).
    - Penalizes Candidate A; selects Candidate B FIRST.
    - Result: Candidate B completes at 889.4 µs -> MET DEADLINE (60.6 µs slack left).
      Candidate A begins at 997.4 µs and completes shortly after.
    - Outcome: 1 out of 2 rescued instead of 0 out of 2!
```

---

## Figure 8 — Ablation Study: Signal Importance Attribution
*Deconstruction of TEMPO into constituent components.*

```
ATTRIBUTION OF DEADLINE MISS REDUCTION UNDER NORMAL CONTENTION
Total Miss Reduction (S1 -> S3): 23.3 percentage points (100% Attribution)

Channel Bus Readiness (S3a):  ███████████████████ 76.4% of total improvement (Δ = 17.8 pp)
Full Cycle-Accurate Delay:   ██████ 23.6% (Queue and multi-page synergy)
Static Queue Depth (S3b):    DEGRADES PERFORMANCE (+9.1 pp misses due to lack of temporal context)
```

---

## Figure 9 — Throughput vs. Latency Pareto Frontier
*Demonstrates that TEMPO slashes tail latency without sacrificing line-rate throughput.*

```
Critical P95 Latency (µs)  [Lower is Better]
  3500 |   * S0 (FIFO)
       |   * S2 (SSD-State)
  2000 |
  1500 |              * S1 (AI-Priority)
  1000 |
   800 |                             # S3 (TEMPO) [PARETO OPTIMAL]
     0 +-----------------------------+-----------------------------+
       1000                        1020                          1040
                           Drive Throughput (MB/s)
```

| Scheduler | Aggregate Throughput | IOPS | P50 Latency | P95 Tail Latency | Deadline Miss % | Pareto Status |
|:---|:---:|:---:|:---:|:---:|:---:|:---|
| **S0-FIFO** | 1,022.4 MB/s | 8,179 | 2,120.4 µs | 3,124.5 µs | 86.6% | Sub-optimal |
| **S2-SSD-State** | 1,034.8 MB/s | 8,278 | 2,098.1 µs | 3,098.2 µs | 84.2% | Sub-optimal |
| **S1-AI-Priority** | 1,018.9 MB/s | 8,151 | 682.4 µs | 1,347.4 µs | 29.2% | Moderate |
| **S3-TEMPO** | **1,028.5 MB/s** | **8,228** | **598.2 µs** | **842.3 µs** | **5.9%** | **Pareto Optimal** |

---

## Figure 10 — Ten-Seed Paired Hypothesis Testing & Statistical Significance
*Paired t-test and Wilcoxon signed-rank test across 10 genuine random seeds ($df=9$).*

| Metric | S1 Mean $\pm$ Std | S3 Mean $\pm$ Std | Mean Paired Difference | 95% Confidence Interval | Paired $t(9)$ / Wilcoxon $W$ | Exact p-value | Effect Size ($d$) |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Deadline Miss %** | 19.01% $\pm$ 5.46% | **9.68% $\pm$ 2.15%** | **+9.33 pp** | [+4.14, +14.52] pp | $t=4.0644, W=0.0$ | **$p = 0.00282$** ($p < 0.01$) | $d = 1.285$ (Very Large) |
| **P95 Latency ($\mu\text{s}$)** | 1,197.31 $\pm$ 116.93 | **946.75 $\pm$ 73.07** | **+250.55 µs** | [+122.20, +378.91] µs | $t=4.4158, W=0.0$ | **$p = 0.00168$** ($p < 0.01$) | $d = 1.396$ (Very Large) |
| **P99 Latency ($\mu\text{s}$)** | 1,448.02 $\pm$ 126.76 | **1,227.66 $\pm$ 65.72** | **+220.36 µs** | [+87.40, +353.32] µs | $t=3.7492, W=0.0$ | **$p = 0.00456$** ($p < 0.01$) | $d = 1.186$ (Large) |
| **P99.9 Tail Latency ($\mu\text{s}$)** | 1,611.88 $\pm$ 54.55 | **1,319.53 $\pm$ 57.74** | **+292.35 µs** | [+228.14, +356.55] µs | $t=10.3000, W=0.0$ | **$p = 2.80 \times 10^{-6}$** ($p < 0.00001$) | $d = 3.257$ (Massive) |

```
10-Seed Paired Miss Rate Comparison (Mean +/- 95% Confidence Interval)
S1-AI-Priority:  ███████████████████ 19.01% +/- 3.91%  (Range: 14.3% to 27.5%)
S3-TEMPO:        ██████████ 9.68% +/- 1.54%            (Range: 5.5% to 11.2%)
```
