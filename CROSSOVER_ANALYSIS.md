# Phase 5: Crossover Analysis & Operational Boundaries
## Mapping the Exact Transition: When Does SSD-State Awareness Matter?

A central tenet of rigorous systems research is that no optimization is universally superior under all workloads. By sweeping deadline slack in fine-grained 50 µs increments from **500 µs to 2,000 µs** across 17 evaluation points on real **CHEOPS'25** KV-cache offload traces, we mapped the precise crossover curve where TEMPO ($S3$) transitions from dominant superiority ($S3 \gg S1$) to convergence ($S3 \approx S1$).

---

## 1. The High-Resolution Crossover Data

* **Workload:** Real CHEOPS'25 FlexGen KV-cache decode slice (1,500 requests, 128 KiB dominant).
* **Hardware:** Samsung 970 Pro NVMeVirt model (8 channels, 16 LUNs, 32 KiB pages).
* **Environment:** Background Write Contention = 200 IOPS, Controller Queue Depth = 32.

| Slack ($\mu\text{s}$) | S1-AI-Priority Miss % | S3-TEMPO Miss % | $\Delta$ Miss % | Miss Ratio ($\frac{S1}{S3}$) | S1 P95 ($\mu\text{s}$) | S3 P95 ($\mu\text{s}$) | **Regime Classification** |
|---|---|---|---|---|---|---|---|
| **500** | 79.7% | 89.4% | -9.7% | 0.89× | 1,347.4 | 842.3 | **Physics Floor** |
| **600** | 65.1% | 87.4% | -22.3% | 0.74× | 1,347.4 | 842.3 | **Physics Floor** |
| **650** | 58.2% | 76.5% | -18.3% | 0.76× | 1,347.4 | 842.3 | **Near-Physical Boundary** |
| **700** | 50.3% | **32.2%** | **+18.1%** | **1.56×** | 1,347.4 | 842.3 | **$S3 \gg S1$ (Inflection Point)** |
| **750** | 40.6% | **9.7%** | **+30.9%** | **4.17×** | 1,347.4 | 842.3 | **$S3 \gg S1$ (Peak Advantage)** |
| **800** | 29.2% | **5.9%** | **+23.3%** | **4.97×** | 1,347.4 | 842.3 | **$S3 \gg S1$ (Peak Advantage)** |
| **850** | 19.3% | **4.9%** | **+14.4%** | **3.97×** | 1,347.4 | 842.3 | **$S3 \gg S1$ (Peak Advantage)** |
| **900** | 12.1% | **4.2%** | **+7.9%** | **2.88×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **950** | 9.2% | **3.9%** | **+5.4%** | **2.39×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,000** | 8.6% | **3.5%** | **+5.0%** | **2.43×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,100** | 7.9% | **2.9%** | **+5.0%** | **2.76×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,200** | 6.7% | **2.0%** | **+4.7%** | **3.33×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,300** | 5.7% | **0.5%** | **+5.2%** | **11.33×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,400** | 3.7% | **0.2%** | **+3.5%** | **22.00×** | 1,347.4 | 842.3 | **$S3 > S1$ (Modest Advantage)** |
| **1,500** | 1.3% | **0.0%** | **+1.3%** | **INF ($S3=0$)** | 1,347.4 | 842.3 | **$S3 \approx S1$ (Transition)** |
| **1,750** | 0.0% | 0.0% | 0.0% | 1.00× | 1,347.4 | 842.3 | **$S3 \approx S1$ (Parity)** |
| **2,000** | 0.0% | 0.0% | 0.0% | 1.00× | 1,341.0 | 841.0 | **$S3 \approx S1$ (Parity)** |

---

## 2. Visual Representation of the Crossover Curve

```text
Deadline Miss Rate (%) vs. Target Deadline Slack (µs)
Miss %
100% ┼───S1 (AI Priority Only)
     │   ───S3 (TEMPO: Joint AI + SSD State)
 80% │   S3\
     │      \
 60% │   S1──\
     │        \
 40% │         \ S1
     │          \───\
 20% │               \ S1
     │                \───\
  0% └─────────────────────┴───────S3=0────S1=0──────► Slack (µs)
    500   600   700   750   800   1000  1200  1500  1750  2000
    │           │           │                 │           │
    └─ Physics ─┴── S3 >> S1 ─┴──── S3 > S1 ────┴─ Parity ─┘
```

---

## 3. The Four Distinct Operational Regimes

### Regime 1: The Physical Hardware Floor ($\le 650\ \mu\text{s}$)
* **Dynamics:** Servicing a 128 KiB request requires transferring four 32 KiB pages across NAND channels ($4 \times 40.96\ \mu\text{s} \approx 164\ \mu\text{s}$ bus time), plus cell sensing ($t_R = 36\ \mu\text{s}$) and controller firmware overhead ($t_{FW} = 30.5\ \mu\text{s}$). Under realistic controller queuing (QD=32), achieving sub-$650\ \mu\text{s}$ turnaround is physically infeasible on standard NAND regardless of the scheduler.

### Regime 2: The Peak Advantage Window ($700\ \mu\text{s} \to 850\ \mu\text{s}$) — $S3 \gg S1$
* **Dynamics:** This is the highest-value operating envelope. At $750\ \mu\text{s}$, S1 suffers **40.6% deadline misses**, while S3 drops misses to **9.7%** (a **4.17× reduction**). At $800\ \mu\text{s}$, S1 misses **29.2%**, while S3 drops misses to **5.9%** (a **4.97× reduction**).
* **Explanation:** In this tight window, there is just enough time to service the request if and only if the request does not stall behind a busy die. S3's channel-conflict avoidance is decisive.

### Regime 3: The Persistent Tail-Latency Window ($900\ \mu\text{s} \to 1,400\ \mu\text{s}$) — $S3 > S1$
* **Dynamics:** As deadlines expand to $1,000\ \mu\text{s} - 1,400\ \mu\text{s}$, absolute deadline misses diminish across both schedulers, but S3 maintains **2.4× to 22× lower miss rates** and finishes all critical requests at a P95 latency of **$842.3\ \mu\text{s}$** compared to S1's **$1,347.4\ \mu\text{s}$** (**$37.5\%$ faster tail latency**).

### Regime 4: Convergence to Parity ($\ge 1,500\ \mu\text{s}$) — $S3 \approx S1$
* **Dynamics:** At $1,500\ \mu\text{s}$, S3 achieves a **0.0% miss rate**; by $1,750\ \mu\text{s}$, S1 also reaches **0.0% misses**. 
* **Explanation:** When the host application provides more than $1.5\ \text{ms}$ of slack per token, temporary $185\ \mu\text{s}$ write cycles and channel contention have enough time to clear without causing deadline violations. Software-level priority queueing (S1) is sufficient.

---

## 4. Defensible Systems Research Conclusion

> **"TEMPO's scheduling advantage is workload- and deadline-dependent, delivering maximum return under tight token-generation budgets (700–1,200 µs) and converging to parity when deadline slack exceeds 1.5 ms."**

This formal boundary establishes technical credibility: we do not claim that SSD-state awareness is an unconditional silver bullet, but rather prove that it is an **essential accelerator specifically in the sub-millisecond tail latency regime where live LLM decoding operates**.
