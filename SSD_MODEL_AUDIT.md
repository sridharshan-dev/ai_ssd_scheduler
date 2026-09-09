# Comprehensive SSD Model Audit & Provenance Specification

This document conducts a rigorous audit of the SSD simulation model implemented in `ai_ssd_scheduler`. It records the exact architectural semantics, equations, timing parameters, and their specific provenance to ensure experimental reproducibility and eliminate simulator artifacts.

---

## 1. Provenance & Parameter Audit Table

| Parameter / Subsystem | Simulator Value | Source & Provenance | Confidence | Validation / Grounding |
|---|---|---|---|---|
| **Channels** | 8 | NVMeVirt (`ssd_config.h` / Samsung 970 Pro baseline) | **High** | Industry-standard NVMe architecture (8-channel controller). |
| **LUNs (Dies) per Channel** | 2 (16 dies total) | NVMeVirt (`ssd_config.h` / Samsung 970 Pro baseline) | **High** | Standard dual-die package stacking per channel. |
| **Flash Page Size** | 32 KiB | NVMeVirt (`ssd_config.h`) | **High** | Modern V-NAND MLC/TLC page granularity (32 KiB). |
| **Channel Bandwidth** | 800 MB/s per channel (6.4 GB/s aggregate) | NVMeVirt (`ssd_config.h` Toggle DDR 3.0/4.0 rate) | **High** | $800\ \text{MB/s} = 800\ \text{bytes}/\mu\text{s}$. Bus transfer time for 32 KiB page: $32768 / 800 = 40.96\ \mu\text{s}$. |
| **NAND Page Read ($t_R$)** | 36.0 µs | NVMeVirt (`ssd_config.h` Samsung 970 Pro $t_R$) | **High** | Published hardware timing for Samsung 64L/96L V-NAND sensing. |
| **NAND Page Program ($t_{PROG}$)** | 185.0 µs | NVMeVirt (`ssd_config.h` Samsung 970 Pro $t_{PROG}$) | **High** | Fast SLC/MLC buffer programming latency reported in emulator. |
| **Firmware Read Overhead ($t_{FW}$)** | 30.5 µs | NVMeVirt (`ssd_config.h` firmware read delay) | **High** | Fixed controller command processing and PCIe DMA setup delay. |
| **Erase Latency ($t_{BERS}$)** | 3.5 ms (3,500 µs) | Flash datasheet / Engineering whitepaper (`unified_ai_ssd_bottlenecks_master.pdf`) | **Experimental** | Standard 3D V-NAND block erase latency range (3.5–12 ms). |
| **Queue Depth (Max In-Flight)** | 32 requests | NVMe Specification default / Host Driver SQ depth | **High** | Linux kernel default NVMe queue depth commonly set to 32–64. |
| **Request Striping Unit** | 32 KiB page round-robin | Standard SSD Controller RAID-0 FTL Interleaving | **High** | Strips 128 KiB requests across 4 consecutive channels. |
| **SSD DRAM Cache** | Uncached (Direct Flash Media Path) | CHEOPS'25 / NVMeVirt conservative baseline | **Controlled** | Assumes cold write buffer / sustained writes bypass DRAM cache to test raw media contention. |
| **GC Pause Model** | Injected synthetic $t_{BERS}$ die lock | Experimental design (Step 7 / Step 8) | **Experimental** | Locks target (Channel, LUN) for 3.5 ms, preventing reads until finished. |

---

## 2. Precise Structural & Semantic Specifications

### 2.1 Hardware Geometry & Hierarchy
The SSD backend is organized hierarchically:
```
SSD Controller (Queue Depth = 32)
 ├── Channel 0 (Half-Duplex Bus: 800 MB/s)
 │    ├── LUN 0 (Die 0)
 │    └── LUN 1 (Die 1)
 ├── Channel 1 (Half-Duplex Bus: 800 MB/s)
 │    ├── LUN 0 (Die 2)
 │    └── LUN 1 (Die 3)
 ...
 └── Channel 7 (Half-Duplex Bus: 800 MB/s)
      ├── LUN 0 (Die 14)
      └── LUN 1 (Die 15)
```

---

### 2.2 Channel Busy Semantics (Half-Duplex Bus)
* **Bus Serialization:** Each of the 8 channels has an independent serialized data bus operating at 800 MB/s.
* **Mutual Exclusion:** Only one LUN attached to a channel can transfer data over the bus at any given time.
* **Transfer Time Calculation:**
  $$\text{TransferTime}(\text{bytes}) = \frac{\text{bytes}}{800\ \text{bytes}/\mu\text{s}}$$
  * For a 32 KiB page: $\frac{32,768}{800} = 40.96\ \mu\text{s}$.
  * For a partial 4 KiB sector: $\frac{4,096}{800} = 5.12\ \mu\text{s}$.

---

### 2.3 LUN (Die) Busy Semantics & Pipelining

Flash dies execute operations independently of the channel bus once triggered:

#### Read Pipeline (`ssd/channel.py:earliest_ready_time`):
1. **LUN Sensing Phase ($t_R = 36\ \mu\text{s}$):**
   * Can begin as soon as the target LUN is idle: $\text{SenseStart} = \max(\text{now}, \text{lun\_busy\_until})$.
   * Completes at $\text{SenseDone} = \text{SenseStart} + 36\ \mu\text{s}$.
   * *During this phase, the channel bus remains completely free for other LUNs on that channel.*
2. **Channel Bus Transfer Phase ($T_{\text{xfer}} = 40.96\ \mu\text{s}$):**
   * Starts when sensing is complete **and** the channel bus is free:
     $$\text{BusStart} = \max(\text{SenseDone}, \text{bus\_busy\_until})$$
   * Finishes at $\text{BusDone} = \text{BusStart} + T_{\text{xfer}}$.
3. **Request Completion:**
   $$\text{CompletionTime} = \text{BusDone} + t_{FW}\ (30.5\ \mu\text{s})$$

#### Write Pipeline (`ssd/channel.py:commit_page_service`):
1. **Channel Bus Transfer Phase ($T_{\text{xfer}} = 40.96\ \mu\text{s}$):**
   * Data must cross the bus into the LUN's internal page buffer first:
     $$\text{BusStart} = \max(\text{now}, \text{bus\_busy\_until})$$
     $$\text{BusDone} = \text{BusStart} + T_{\text{xfer}}$$
2. **LUN Cell Programming Phase ($t_{PROG} = 185\ \mu\text{s}$):**
   * Cell programming begins once transfer is complete and the die is idle:
     $$\text{ProgStart} = \max(\text{BusDone}, \text{lun\_busy\_until})$$
     $$\text{ProgDone} = \text{ProgStart} + 185\ \mu\text{s}$$
   * *Crucial Timing Behavior:* The channel bus is released at $\text{BusDone}$ (after ~41 µs), allowing other LUNs on that channel to transfer data while this LUN programs for the remaining 185 µs!
3. **Request Completion:**
   $$\text{CompletionTime} = \text{ProgDone} + t_{FW}\ (30.5\ \mu\text{s})$$

---

### 2.4 FTL Mapping & Request-to-Channel Interleaving
* Host requests (predominantly 128 KiB from CHEOPS) are decomposed into 32 KiB flash pages (`ssd/backend.py:decompose_request`).
* The Flash Translation Layer (FTL) applies standard multi-channel RAID-0 striping:
  $$\text{BasePage} = \frac{\text{start\_sector} \times 512}{\text{page\_size\_bytes}}$$
  For each sub-page $p \in [0, \dots, \text{num\_pages} - 1]$:
  $$\text{GlobalPageID} = \text{BasePage} + p$$
  $$\text{ChannelID} = \text{GlobalPageID} \pmod 8$$
  $$\text{LunID} = \left(\frac{\text{GlobalPageID}}{8}\right) \pmod 2$$
* **Result for 128 KiB Request:** Spans exactly 4 consecutive channels (e.g. Channels 0, 1, 2, 3), executing in parallel across 4 independent buses and dies.

---

### 2.5 Read/Write Interference & Hardware Contention
* **Same-LUN Conflict:** If a 32 KiB write starts on `(Channel 0, LUN 0)`, that die is locked for $185\ \mu\text{s}$. Any read targeting `(Channel 0, LUN 0)` must queue behind the program cycle.
* **Different-LUN, Same-Channel Conflict:** If `(Channel 0, LUN 0)` is programming, `(Channel 0, LUN 1)` can sense its page in parallel ($36\ \mu\text{s}$), but must wait for the channel bus if a transfer is active.
* **GC Block Erase Lock:** When GC fires on `(Channel C, LUN L)`, the die is marked busy for $3.5\ \text{ms}$ ($3,500\ \mu\text{s}$). Any read or write mapped to that LUN is delayed for the full remaining duration of the erase.

---

### 2.6 What Is Explicitly Modeled vs. Kept Abstract

1. **Explicitly Modeled (Ground Truth):**
   * Cycle-accurate channel bus contention and transfer serialization.
   * Die-level parallel execution and sensing/programming overlap.
   * Multi-page striping across independent channels and LUNs.
   * Write-induced read blocking ($185\ \mu\text{s}$ write penalty).
   * GC block-erase locking ($3.5\ \text{ms}$ pause).
   * Monotonic arrival time queuing and queue-depth capping (QD=32).
2. **Explicitly Not Modeled (Avoid Over-Complication):**
   * *Volatile DRAM Write Buffering:* We assume write caching has saturated (as occurs during active KV-cache checkpoint bursts), exposing raw NAND program latency.
   * *NAND Wear Leveling / Bit Error Rate (BER) drift:* Modeled via macroscopic GC pause events rather than per-block cycle counting.
   * *Host PCIe Bus & Bounce Buffers:* Trace timestamps already reflect the block device arrival at the NVMe driver interface.
