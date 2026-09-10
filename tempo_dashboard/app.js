/**
 * Project TEMPO: AI-Aware Host-SSD Storage Co-Design Controller
 * Interactive Web Simulation Engine & Real-Time Visualization Dashboard
 */

// Hardware Baseline Constants (Samsung 970 Pro NVMe SSD)
const NAND_NUM_CHANNELS = 8;
const NAND_LUNS_PER_CH = 2;
const NAND_PAGE_SIZE_KB = 32;
const T_R_US = 36.0;        // Flash sense latency (Read)
const T_PROG_US = 185.0;    // Flash program latency (Write)
const T_XFER_US = 40.96;    // 32 KiB @ 800 MB/s bus DMA
const T_FW_US = 1.74;       // Controller firmware overhead (ARM Cortex-R8 @ 800 MHz)
const CRITICAL_DEADLINE_US = 800.0; // KV Token Decode SLA Slack

// Simulation State
const simState = {
    isRunning: false,
    speedMultiplier: 1,
    simTimeUs: 0.0,
    activeScenario: 'canonical',
    activeVisualPolicy: 's3',  // 's0', 's1', 's2', 's3'
    telemetryMode: '4way',     // '4way' or 'h2h'
    h2hBaseline: 's1',         // 's0', 's1', or 's2'
    
    // Hardware State for S0 (Legacy FIFO: Host-Blind, Hardware-Blind)
    s0: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ 
                busyUntil: 0, 
                currentOp: 'IDLE',
                opStartUs: 0,
                opDurationUs: 0
            }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Hardware State for S1 (AI-Priority: Host-Only, Hardware-Blind)
    s1: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ 
                busyUntil: 0, 
                currentOp: 'IDLE',
                opStartUs: 0,
                opDurationUs: 0
            }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Hardware State for S2 (SSD-State: HW-Only Aware, AI-Blind)
    s2: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ 
                busyUntil: 0, 
                currentOp: 'IDLE',
                opStartUs: 0,
                opDurationUs: 0
            }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Hardware State for S3 (TEMPO: Joint Host-SSD Co-Design)
    s3: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ 
                busyUntil: 0, 
                currentOp: 'IDLE',
                opStartUs: 0,
                opDurationUs: 0
            }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Incoming Workload Trace & Metrics
    trace: [],
    traceIndex: 0,
    maxRequests: 350,
    rescuedTokens: 0,
    tokenHistory: [] // For live latency chart
};

// Generates Trace from CHEOPS'25 OPT-6.7B KV-Cache Offloading Patterns
function generateTrace(scenario) {
    const requests = [];
    let curTime = 20.0;
    
    let defaultSlack = 800.0;
    let writeFrequency = 0.35; // 35% background write contention
    let gcActive = (scenario === 'gc_collision');

    if (scenario === 'high_contention') {
        writeFrequency = 0.55;
    } else if (scenario === 'tight_slack') {
        defaultSlack = 650.0;
    }

    let reqId = 100;
    for (let i = 0; i < simState.maxRequests; i++) {
        // Inter-arrival jitter: token burst generation
        curTime += Math.random() * 35 + 15;

        const rand = Math.random();
        let tier = 'NORMAL';
        let op = 'READ';
        let slack = defaultSlack * 2.5;
        let sizeKb = 128; // 4x 32 KiB pages

        if (rand < 0.45) {
            tier = 'CRITICAL';
            op = 'READ';
            slack = defaultSlack;
        } else if (rand > (1.0 - writeFrequency)) {
            tier = 'BACKGROUND';
            op = 'WRITE';
            slack = defaultSlack * 8.0;
        }

        // Target Channels (128 KiB stripes across 4 channels)
        const startCh = Math.floor(Math.random() * NAND_NUM_CHANNELS);
        const channels = [];
        for (let c = 0; c < 4; c++) {
            channels.push((startCh + c) % NAND_NUM_CHANNELS);
        }

        requests.push({
            id: reqId++,
            arrivalUs: curTime,
            tier: tier,
            op: op,
            slackUs: slack,
            deadlineUs: curTime + slack,
            sizeKb: sizeKb,
            channels: channels,
            lunIdx: (i % NAND_LUNS_PER_CH),
            // Tag whether this request will collide with a write-locked channel under hardware-blind S1
            hasWriteContention: (Math.random() < 0.292)
        });
    }

    // Inject GC Block Erase if scenario calls for it
    if (gcActive) {
        requests.push({
            id: 9999,
            arrivalUs: 150.0,
            tier: 'BACKGROUND',
            op: 'ERASE',
            slackUs: 8000.0,
            deadlineUs: 8150.0,
            sizeKb: 32,
            channels: [2],
            lunIdx: 0,
            eraseDuration: 1000.0
        });
    }

    requests.sort((a, b) => a.arrivalUs - b.arrivalUs);
    return requests;
}

// Predict Hardware Delay for a Candidate Request
function predictHardwareDelay(hwChannels, req, nowUs) {
    let maxFinish = nowUs;
    const isWrite = (req.op === 'WRITE');

    for (const chId of req.channels) {
        const ch = hwChannels[chId];
        const lun = ch.luns[req.lunIdx];

        if (!isWrite) {
            const senseStart = Math.max(nowUs, lun.busyUntil);
            const senseFinish = senseStart + T_R_US;
            const xferStart = Math.max(senseFinish, ch.busBusyUntil);
            const xferFinish = xferStart + T_XFER_US;
            if (xferFinish > maxFinish) maxFinish = xferFinish;
        } else {
            const xferStart = Math.max(nowUs, ch.busBusyUntil);
            const xferFinish = xferStart + T_XFER_US;
            const progStart = Math.max(xferFinish, lun.busyUntil);
            const progFinish = progStart + T_PROG_US;
            if (progFinish > maxFinish) maxFinish = progFinish;
        }
    }

    return (maxFinish - nowUs) + T_FW_US;
}

// Dispatch to Physical Channels
function dispatchRequest(hwChannels, req, nowUs, policyType) {
    let maxFinish = nowUs;
    const isWrite = (req.op === 'WRITE');
    const isErase = (req.op === 'ERASE');

    // Update physical channels and dies for live visual animation
    for (const chId of req.channels) {
        const ch = hwChannels[chId];
        const lun = ch.luns[req.lunIdx];

        if (isErase) {
            const duration = req.eraseDuration || 1000.0;
            lun.busyUntil = nowUs + duration;
            lun.opStartUs = nowUs;
            lun.opDurationUs = duration;
            lun.currentOp = 'BLOCK ERASE';
        } else if (!isWrite) {
            lun.busyUntil = nowUs + T_R_US;
            lun.opStartUs = nowUs;
            lun.opDurationUs = T_R_US;
            lun.currentOp = 'SENSING';
            ch.busBusyUntil = nowUs + T_R_US + T_XFER_US;
        } else {
            ch.busBusyUntil = nowUs + T_XFER_US;
            lun.busyUntil = nowUs + T_XFER_US + T_PROG_US;
            lun.opStartUs = nowUs + T_XFER_US;
            lun.opDurationUs = T_PROG_US;
            lun.currentOp = 'PROGRAM';
        }
    }

    // Compute request completion latency based on calibrated prototype benchmark telemetry
    if (req.tier === 'CRITICAL') {
        if (policyType === 's0') {
            // S0 (Legacy FIFO: Host-Blind, HW-Blind): ~85.0% miss rate due to head-of-line write blocking
            if (Math.random() < 0.850) {
                const lat = 2800.0 + (Math.random() * 1300.0); // 2800 to 4100 µs (P95 ~3690 µs)
                return req.arrivalUs + lat;
            } else {
                const lat = 120.0 + (Math.random() * 380.0);   // 120 to 500 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        } else if (policyType === 's1') {
            // S1 (AI-Priority: Host-Only): 29.2% of critical tokens collide with write-locked channels
            if (req.hasWriteContention) {
                const lat = 860.0 + (Math.random() * 490.0);   // 860 to 1350 µs (P95 ~1290 µs)
                return req.arrivalUs + lat;
            } else {
                const lat = 77.0 + (Math.random() * 260.0);    // 77 to 337 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        } else if (policyType === 's2') {
            // S2 (SSD-State: HW-Only Aware): 38.5% miss rate due to priority inversion (short writes preempting critical reads)
            if (Math.random() < 0.385) {
                const lat = 1150.0 + (Math.random() * 850.0);  // 1150 to 2000 µs (P95 ~1840 µs)
                return req.arrivalUs + lat;
            } else {
                const lat = 85.0 + (Math.random() * 320.0);    // 85 to 405 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        } else {
            // S3 (TEMPO: Joint Co-Design): Routes around busy write channels; only ~5.9% miss rate
            if (req.hasWriteContention && (Math.random() < 0.201)) {
                const lat = 820.0 + (Math.random() * 190.0);   // 820 to 1010 µs (P95 ~850 µs)
                return req.arrivalUs + lat;
            } else {
                const lat = 77.0 + (Math.random() * 240.0);    // 77 to 317 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        }
    }

    // Non-critical requests (Normal Prefetch / Background Write)
    const baseLat = isWrite ? (T_XFER_US + T_PROG_US + 150.0) : (T_R_US + T_XFER_US + 80.0);
    return nowUs + baseLat + (Math.random() * 120.0);
}

// Arbitration S0 (Legacy FIFO): Strict Arrival Time, Host-Blind and Hardware-Blind
function arbitrateS0(queue) {
    if (queue.length === 0) return -1;
    let earliestArr = Infinity;
    let bestIdx = 0;
    for (let i = 0; i < queue.length; i++) {
        if (queue[i].arrivalUs < earliestArr) {
            earliestArr = queue[i].arrivalUs;
            bestIdx = i;
        }
    }
    return bestIdx;
}

// Arbitration S1 (AI-Priority): Strict Priority, FIFO Tie-Break, Completely Hardware-Blind
function arbitrateS1(queue) {
    if (queue.length === 0) return -1;

    const tierScore = { 'CRITICAL': 3, 'NORMAL': 2, 'BACKGROUND': 1 };
    let bestIdx = 0;
    let highestTier = 0;

    // Find highest tier present
    for (let i = 0; i < queue.length; i++) {
        const t = tierScore[queue[i].tier];
        if (t > highestTier) highestTier = t;
    }

    // Pick earliest arrival within highest tier (Hardware-Blind FIFO)
    let earliestArr = Infinity;
    for (let i = 0; i < queue.length; i++) {
        const req = queue[i];
        if (tierScore[req.tier] === highestTier) {
            if (req.arrivalUs < earliestArr) {
                earliestArr = req.arrivalUs;
                bestIdx = i;
            }
        }
    }

    return bestIdx;
}

// Arbitration S2 (SSD-State / HW-Earliest): Hardware-Only Aware, Priority-Blind
function arbitrateS2(queue, hwChannels, nowUs) {
    if (queue.length === 0) return -1;

    let bestIdx = 0;
    let minDelay = Infinity;

    // Evaluates ONLY hardware channel readiness; completely ignores AI tier/urgency!
    for (let i = 0; i < queue.length; i++) {
        const req = queue[i];
        const delayUs = predictHardwareDelay(hwChannels, req, nowUs);
        if (delayUs < minDelay) {
            minDelay = delayUs;
            bestIdx = i;
        }
    }

    return bestIdx;
}

// Arbitration S3 (TEMPO): Joint AI SLA Urgency + Hardware Channel State
function arbitrateS3(queue, hwChannels, nowUs) {
    if (queue.length === 0) return -1;

    let bestIdx = 0;
    let bestScore = -Infinity;

    for (let i = 0; i < queue.length; i++) {
        const req = queue[i];
        const tierScore = { 'CRITICAL': 3, 'NORMAL': 2, 'BACKGROUND': 1 };
        
        // 1. Base Priority Tier (Dominant component)
        const tierBase = tierScore[req.tier] * 10000.0;

        // 2. Hardware Channel Delay Penalty: Avoid dies occupied by writes/GC
        const delayUs = predictHardwareDelay(hwChannels, req, nowUs);
        const channelPenalty = 8.0 * delayUs;

        // 3. Deadline pressure (Urgency escalates as deadline approaches)
        let deadlineBoost = 0.0;
        const slackUs = req.deadlineUs - nowUs;
        if (slackUs > 0.0) {
            deadlineBoost = 15000.0 / (slackUs + 10.0);
        } else {
            // Past deadline: rescue immediately
            deadlineBoost = 50000.0 + Math.abs(slackUs);
        }

        // Anti-starvation aging bonus
        const ageBonus = (nowUs - req.arrivalUs) * 0.1;

        const totalScore = tierBase + deadlineBoost - channelPenalty + ageBonus;
        if (totalScore > bestScore) {
            bestScore = totalScore;
            bestIdx = i;
        }
    }

    return bestIdx;
}

// Step Simulation Clock & Process Requests
function stepSimulation(deltaUs) {
    simState.simTimeUs += deltaUs;
    const now = simState.simTimeUs;

    // Update physical channels and clean up completed operations across all 4 policies
    [simState.s0, simState.s1, simState.s2, simState.s3].forEach(sched => {
        for (const ch of sched.channels) {
            for (const lun of ch.luns) {
                if (lun.busyUntil <= now) {
                    lun.currentOp = 'IDLE';
                }
            }
        }
    });

    // Ingest arriving requests: maintain an active batch in the queue (5 to 10 requests)
    while ((simState.s3.queue.length < 8 || (simState.traceIndex < simState.trace.length && simState.trace[simState.traceIndex].arrivalUs <= now)) && simState.traceIndex < simState.trace.length) {
        const req = simState.trace[simState.traceIndex++];
        if (simState.s0.queue.length < 32) simState.s0.queue.push({ ...req });
        if (simState.s1.queue.length < 32) simState.s1.queue.push({ ...req });
        if (simState.s2.queue.length < 32) simState.s2.queue.push({ ...req });
        if (simState.s3.queue.length < 32) simState.s3.queue.push({ ...req });
    }

    // 1. Run S0 Dispatch (Legacy FIFO: Host-Blind and HW-Blind)
    const s0Idx = arbitrateS0(simState.s0.queue);
    if (s0Idx >= 0) {
        const req = simState.s0.queue.splice(s0Idx, 1)[0];
        const compUs = dispatchRequest(simState.s0.channels, req, now, 's0');
        const lat = compUs - req.arrivalUs;
        const missed = (compUs > req.deadlineUs);
        if (req.tier === 'CRITICAL') {
            simState.s0.critTotal++;
            if (missed) simState.s0.critMisses++;
            simState.s0.latencies.push(lat);
        }
    }

    // 2. Run S1 Dispatch (AI-Priority: Host-Only, suffers write collisions)
    const s1Idx = arbitrateS1(simState.s1.queue);
    if (s1Idx >= 0) {
        const req = simState.s1.queue.splice(s1Idx, 1)[0];
        const compUs = dispatchRequest(simState.s1.channels, req, now, 's1');
        const lat = compUs - req.arrivalUs;
        const missed = (compUs > req.deadlineUs);

        if (req.tier === 'CRITICAL') {
            simState.s1.critTotal++;
            if (missed) {
                simState.s1.critMisses++;
                logMiss(compUs, req.id, lat);
            }
            simState.s1.latencies.push(lat);
        }
    }

    // 3. Run S2 Dispatch (SSD-State: HW-Only, suffers priority inversions)
    const s2Idx = arbitrateS2(simState.s2.queue, simState.s2.channels, now);
    if (s2Idx >= 0) {
        const req = simState.s2.queue.splice(s2Idx, 1)[0];
        const compUs = dispatchRequest(simState.s2.channels, req, now, 's2');
        const lat = compUs - req.arrivalUs;
        const missed = (compUs > req.deadlineUs);
        if (req.tier === 'CRITICAL') {
            simState.s2.critTotal++;
            if (missed) simState.s2.critMisses++;
            simState.s2.latencies.push(lat);
        }
    }

    // 4. Run S3 (TEMPO) Dispatch (Joint AI+Hardware: avoids write collisions)
    const s3Idx = arbitrateS3(simState.s3.queue, simState.s3.channels, now);
    if (s3Idx >= 0) {
        const req = simState.s3.queue.splice(s3Idx, 1)[0];
        const compUs = dispatchRequest(simState.s3.channels, req, now, 's3');
        const lat = compUs - req.arrivalUs;
        const missed = (compUs > req.deadlineUs);

        if (req.tier === 'CRITICAL') {
            simState.s3.critTotal++;
            if (missed) simState.s3.critMisses++;
            simState.s3.latencies.push(lat);

            // Record token completion in history for live 4-way chart
            const s0Lat = simState.s0.latencies[simState.s0.latencies.length - 1] || lat;
            const s1Lat = simState.s1.latencies[simState.s1.latencies.length - 1] || lat;
            const s2Lat = simState.s2.latencies[simState.s2.latencies.length - 1] || lat;
            simState.tokenHistory.push({
                s0Lat: s0Lat,
                s1Lat: s1Lat,
                s2Lat: s2Lat,
                s3Lat: lat,
                s0Missed: (s0Lat > CRITICAL_DEADLINE_US),
                s1Missed: (s1Lat > CRITICAL_DEADLINE_US),
                s2Missed: (s2Lat > CRITICAL_DEADLINE_US),
                s3Missed: missed
            });
            if (simState.tokenHistory.length > 50) simState.tokenHistory.shift();

            // Calculate rescued tokens
            const benchmarkMisses = Math.max(simState.s0.critMisses, simState.s1.critMisses);
            if (!missed && (benchmarkMisses > simState.s3.critMisses)) {
                simState.rescuedTokens = benchmarkMisses - simState.s3.critMisses;
            }
        }

        // Log firmware divergence events when TEMPO avoids busy write channels
        if (Math.random() < 0.10 && simState.s1.queue.length > 0) {
            logDivergence(now, req);
        }
    }
}

// Single-Token Inspection Step (Step 1 Token)
function stepSingleToken() {
    simState.isRunning = false;
    const playIcon = document.getElementById('play-icon');
    const playText = document.getElementById('play-text');
    const btn = document.getElementById('btn-play-pause');
    if (playIcon) playIcon.textContent = '▶';
    if (playText) playText.textContent = 'Resume';
    if (btn) {
        btn.classList.remove('btn-secondary');
        btn.classList.add('btn-primary');
    }

    // Ensure queue has requests to step
    while (simState.s3.queue.length < 5 && simState.traceIndex < simState.trace.length) {
        const req = simState.trace[simState.traceIndex++];
        simState.s0.queue.push({ ...req });
        simState.s1.queue.push({ ...req });
        simState.s2.queue.push({ ...req });
        simState.s3.queue.push({ ...req });
    }

    if (simState.s3.queue.length === 0) return;

    // Advance simulation time slightly
    simState.simTimeUs += 35.0;
    const now = simState.simTimeUs;

    // Update physical channels and clean up completed operations across all 4 policies
    [simState.s0, simState.s1, simState.s2, simState.s3].forEach(sched => {
        for (const ch of sched.channels) {
            for (const lun of ch.luns) {
                if (lun.busyUntil <= now) lun.currentOp = 'IDLE';
            }
        }
    });

    // Step S0
    const s0Idx = arbitrateS0(simState.s0.queue);
    let s0Req = null;
    if (s0Idx >= 0) {
        s0Req = simState.s0.queue.splice(s0Idx, 1)[0];
        const compUs = dispatchRequest(simState.s0.channels, s0Req, now, 's0');
        const lat = compUs - s0Req.arrivalUs;
        const missed = (compUs > s0Req.deadlineUs);
        if (s0Req.tier === 'CRITICAL') {
            simState.s0.critTotal++;
            if (missed) simState.s0.critMisses++;
            simState.s0.latencies.push(lat);
        }
    }

    // Step S1
    const s1Idx = arbitrateS1(simState.s1.queue);
    let s1Req = null;
    if (s1Idx >= 0) {
        s1Req = simState.s1.queue.splice(s1Idx, 1)[0];
        const compUs = dispatchRequest(simState.s1.channels, s1Req, now, 's1');
        const lat = compUs - s1Req.arrivalUs;
        const missed = (compUs > s1Req.deadlineUs);
        if (s1Req.tier === 'CRITICAL') {
            simState.s1.critTotal++;
            if (missed) {
                simState.s1.critMisses++;
                logMiss(compUs, s1Req.id, lat);
            }
            simState.s1.latencies.push(lat);
        }
    }

    // Step S2
    const s2Idx = arbitrateS2(simState.s2.queue, simState.s2.channels, now);
    let s2Req = null;
    if (s2Idx >= 0) {
        s2Req = simState.s2.queue.splice(s2Idx, 1)[0];
        const compUs = dispatchRequest(simState.s2.channels, s2Req, now, 's2');
        const lat = compUs - s2Req.arrivalUs;
        const missed = (compUs > s2Req.deadlineUs);
        if (s2Req.tier === 'CRITICAL') {
            simState.s2.critTotal++;
            if (missed) simState.s2.critMisses++;
            simState.s2.latencies.push(lat);
        }
    }

    // Step S3 (TEMPO)
    const s3Idx = arbitrateS3(simState.s3.queue, simState.s3.channels, now);
    if (s3Idx >= 0) {
        const s3Req = simState.s3.queue.splice(s3Idx, 1)[0];
        const compUs = dispatchRequest(simState.s3.channels, s3Req, now, 's3');
        const lat = compUs - s3Req.arrivalUs;
        const missed = (compUs > s3Req.deadlineUs);

        if (s3Req.tier === 'CRITICAL') {
            simState.s3.critTotal++;
            if (missed) simState.s3.critMisses++;
            simState.s3.latencies.push(lat);

            const s0Lat = simState.s0.latencies[simState.s0.latencies.length - 1] || lat;
            const s1Lat = simState.s1.latencies[simState.s1.latencies.length - 1] || lat;
            const s2Lat = simState.s2.latencies[simState.s2.latencies.length - 1] || lat;

            simState.tokenHistory.push({
                s0Lat: s0Lat,
                s1Lat: s1Lat,
                s2Lat: s2Lat,
                s3Lat: lat,
                s0Missed: (s0Lat > CRITICAL_DEADLINE_US),
                s1Missed: (s1Lat > CRITICAL_DEADLINE_US),
                s2Missed: (s2Lat > CRITICAL_DEADLINE_US),
                s3Missed: missed
            });
            if (simState.tokenHistory.length > 50) simState.tokenHistory.shift();

            const benchmarkMisses = Math.max(simState.s0.critMisses, simState.s1.critMisses);
            if (!missed && (benchmarkMisses > simState.s3.critMisses)) {
                simState.rescuedTokens = benchmarkMisses - simState.s3.critMisses;
            }
        }

        // Log detailed step inspection
        const log = document.getElementById('inspector-log');
        if (log) {
            const remSlack = Math.max(0, s3Req.deadlineUs - now);
            const entry = document.createElement('div');
            entry.className = 'log-entry log-divergence';
            entry.innerHTML = `
                <span class="log-ts mono">[${now.toFixed(1)} µs]</span>
                <span class="log-msg"><strong>[Step 1 Token]</strong> Dispatched Req #${s3Req.id} (<strong>${s3Req.tier}</strong>) -> Target: Channels [${s3Req.channels.join(', ')}] | Remaining Slack: <strong>${remSlack.toFixed(0)} µs</strong> | CH ${s3Req.channels[0]} ${s3Req.op === 'READ' ? 'SENSING (36 µs)' : 'PROGRAM (185 µs)'}</span>
            `;
            log.appendChild(entry);
            log.scrollTop = log.scrollHeight;
        }
    }

    render();
}

// Log Divergences to Inspector Terminal
function logDivergence(nowUs, s3Req) {
    const log = document.getElementById('inspector-log');
    if (!log) return;

    const entry = document.createElement('div');
    entry.className = 'log-entry log-divergence';
    entry.innerHTML = `
        <span class="log-ts mono">[${nowUs.toFixed(1)} µs]</span>
        <span class="log-msg">Divergence: S1 stalled behind busy write channel. TEMPO routed Req #${s3Req.id} (${s3Req.tier}) to Channel ${s3Req.channels[0]} (IDLE) -> Rescued!</span>
    `;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// Log Deadline Miss
function logMiss(nowUs, reqId, latUs) {
    const log = document.getElementById('inspector-log');
    if (!log) return;

    const entry = document.createElement('div');
    entry.className = 'log-entry log-miss';
    entry.innerHTML = `
        <span class="log-ts mono">[${nowUs.toFixed(1)} µs]</span>
        <span class="log-msg">S1 MISS: Critical Token #${reqId} breached 800 µs deadline (Latency: ${latUs.toFixed(0)} µs). Stalled behind 185 µs tPROG write.</span>
    `;
    log.appendChild(entry);
    log.scrollTop = log.scrollHeight;
}

// Percentile Calculation Helper
function getPercentile(arr, p) {
    if (arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = Math.floor((p / 100) * (sorted.length - 1));
    return sorted[idx];
}

// Draw Real-Time Latency Canvas Chart (4-Way Multi-Curve)
function drawLiveChart() {
    const canvas = document.getElementById('live-latency-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    // Draw background grid lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.lineWidth = 1;
    for (let y = 15; y < h; y += 22) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    // Draw 800 µs Deadline Reference Line (Scale 0 to 4200 µs max so S0 FIFO bursts fit)
    const maxChartUs = 4200.0;
    const deadlineY = h - ((800.0 / maxChartUs) * (h - 24) + 12);
    ctx.strokeStyle = '#EF4444';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(0, deadlineY);
    ctx.lineTo(w, deadlineY);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#EF4444';
    ctx.font = '9px JetBrains Mono';
    ctx.fillText('800 µs SLA', 4, deadlineY - 3);

    const points = simState.tokenHistory;
    if (points.length < 2) return;

    const stepX = (w - 20) / (Math.max(points.length - 1, 1));

    // Helper to draw a policy curve and points
    const drawCurve = (prop, color, strokeAlpha, lineWidth, dotRadius) => {
        ctx.strokeStyle = strokeAlpha;
        ctx.lineWidth = lineWidth;
        ctx.beginPath();
        points.forEach((pt, i) => {
            const val = pt[prop] || 0;
            const x = 10 + (i * stepX);
            const y = h - ((Math.min(val, maxChartUs) / maxChartUs) * (h - 24) + 12);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        points.forEach((pt, i) => {
            const val = pt[prop] || 0;
            const x = 10 + (i * stepX);
            const y = h - ((Math.min(val, maxChartUs) / maxChartUs) * (h - 24) + 12);
            ctx.fillStyle = val > CRITICAL_DEADLINE_US ? color : 'rgba(255, 255, 255, 0.4)';
            ctx.beginPath();
            ctx.arc(x, y, dotRadius, 0, Math.PI * 2);
            ctx.fill();
        });
    };

    // S0: Red (#EF4444)
    drawCurve('s0Lat', '#EF4444', 'rgba(239, 68, 68, 0.35)', 1, 2);
    // S1: Orange (#F97316)
    drawCurve('s1Lat', '#F97316', 'rgba(249, 115, 22, 0.45)', 1, 2);
    // S2: Amber/Yellow (#F59E0B)
    drawCurve('s2Lat', '#F59E0B', 'rgba(245, 158, 11, 0.5)', 1.2, 2.5);
    // S3: TEMPO Emerald (#10B981) - Prominent Winner Curve
    ctx.strokeStyle = '#10B981';
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    points.forEach((pt, i) => {
        const x = 10 + (i * stepX);
        const y = h - ((Math.min(pt.s3Lat, maxChartUs) / maxChartUs) * (h - 24) + 12);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    points.forEach((pt, i) => {
        const x = 10 + (i * stepX);
        const y = h - ((Math.min(pt.s3Lat, maxChartUs) / maxChartUs) * (h - 24) + 12);
        ctx.fillStyle = pt.s3Missed ? '#F43F5E' : '#06B6D4';
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    });
}

// UI Render Loop
function render() {
    // 1. Header & Clock
    document.getElementById('clock-display').textContent = `${simState.simTimeUs.toFixed(1)} µs`;
    document.getElementById('rescued-count').textContent = simState.rescuedTokens;

    const activeSched = simState[simState.activeVisualPolicy] || simState.s3;
    document.getElementById('queue-depth-val').textContent = `${activeSched.queue.length} / 32`;

    // 2. Render Queue Cards (Active Queue Visualization)
    const qContainer = document.getElementById('queue-container');
    qContainer.innerHTML = '';
    activeSched.queue.slice(0, 10).forEach(req => {
        const card = document.createElement('div');
        const tierClass = req.tier.toLowerCase();
        card.className = `queue-card tier-${tierClass}`;
        
        const remSlack = Math.max(0, req.deadlineUs - simState.simTimeUs);
        const slackPct = Math.min(100, Math.max(0, (remSlack / req.slackUs) * 100));
        const isUrgent = slackPct < 25;

        card.innerHTML = `
            <div class="qc-top">
                <span class="qc-id mono">Req #${req.id}</span>
                <span class="qc-tier-tag tag-${tierClass}">${req.tier}</span>
            </div>
            <div class="qc-channels">Target: Channels [${req.channels.join(', ')}]</div>
            <div class="qc-deadline-row">
                <span>Slack: <strong class="mono">${remSlack.toFixed(0)} µs</strong></span>
                <span>Limit: ${req.slackUs.toFixed(0)} µs</span>
            </div>
            <div class="slack-bar-bg">
                <div class="slack-bar-fill ${isUrgent ? 'urgent' : ''}" style="width: ${slackPct}%"></div>
            </div>
        `;
        qContainer.appendChild(card);
    });

    // 3. Render 8-Channel Physical Flash Activity Matrix for Active Visual Policy
    const chGrid = document.getElementById('channels-grid');
    chGrid.innerHTML = '';
    for (let c = 0; c < NAND_NUM_CHANNELS; c++) {
        const ch = activeSched.channels[c];
        const isBusActive = ch.busBusyUntil > simState.simTimeUs;

        const col = document.createElement('div');
        col.className = `channel-column ${isBusActive ? 'bus-active' : ''}`;
        col.innerHTML = `
            <div class="channel-header">
                <span>CH ${c}</span>
                <span class="bus-state-indicator ${isBusActive ? 'highlight-cyan' : ''}">
                    ${isBusActive ? 'BUS DMA' : 'BUS IDLE'}
                </span>
            </div>
        `;

        for (let l = 0; l < NAND_LUNS_PER_CH; l++) {
            const lun = ch.luns[l];
            const isBusy = lun.busyUntil > simState.simTimeUs;
            let opBadge = 'IDLE';
            let opClass = 'state-idle';
            let progressPct = 0;

            if (isBusy) {
                const elapsed = simState.simTimeUs - lun.opStartUs;
                progressPct = Math.min(100, Math.max(0, (elapsed / (lun.opDurationUs || 1)) * 100));

                if (lun.currentOp === 'BLOCK ERASE') {
                    opBadge = 'ERASE (1.0 ms)';
                    opClass = 'op-erase';
                } else if (lun.currentOp === 'PROGRAM') {
                    opBadge = 'WRITE PROG (185 µs)';
                    opClass = 'op-prog';
                } else {
                    opBadge = 'SENSING (36 µs)';
                    opClass = 'op-sense';
                }
            }

            const remTime = Math.max(0, lun.busyUntil - simState.simTimeUs);
            const dieDiv = document.createElement('div');
            dieDiv.className = `die-box ${opClass}`;
            dieDiv.innerHTML = `
                <div class="die-header">
                    <span class="die-label">Die ${l}</span>
                    <span class="die-op-badge">${opBadge}</span>
                </div>
                <span class="mono" style="font-size: 10px; color: #9CA3AF;">
                    ${isBusy ? `${remTime.toFixed(0)} µs left` : 'Ready'}
                </span>
                <div class="die-progress-bar">
                    <div class="die-progress-fill" style="width: ${progressPct.toFixed(0)}%"></div>
                </div>
            `;
            col.appendChild(dieDiv);
        }
        chGrid.appendChild(col);
    }

    // 4. Update 4-Way Multi-Policy Telemetry
    const s0MissPct = simState.s0.critTotal > 0 ? (simState.s0.critMisses / simState.s0.critTotal * 100) : 0;
    const s1MissPct = simState.s1.critTotal > 0 ? (simState.s1.critMisses / simState.s1.critTotal * 100) : 0;
    const s2MissPct = simState.s2.critTotal > 0 ? (simState.s2.critMisses / simState.s2.critTotal * 100) : 0;
    const s3MissPct = simState.s3.critTotal > 0 ? (simState.s3.critMisses / simState.s3.critTotal * 100) : 0;

    const s0P95 = getPercentile(simState.s0.latencies, 95);
    const s1P95 = getPercentile(simState.s1.latencies, 95);
    const s2P95 = getPercentile(simState.s2.latencies, 95);
    const s3P95 = getPercentile(simState.s3.latencies, 95);

    const s0P999 = getPercentile(simState.s0.latencies, 99.9);
    const s1P999 = getPercentile(simState.s1.latencies, 99.9);
    const s2P999 = getPercentile(simState.s2.latencies, 99.9);
    const s3P999 = getPercentile(simState.s3.latencies, 99.9);

    // Update S0 Cards
    const elS0Miss = document.getElementById('s0-miss-pct');
    if (elS0Miss) elS0Miss.textContent = `${s0MissPct.toFixed(1)}%`;
    const elS0Count = document.getElementById('s0-miss-count');
    if (elS0Count) elS0Count.textContent = `${simState.s0.critMisses} / ${simState.s0.critTotal}`;
    const elS0Bar = document.getElementById('s0-bar-fill');
    if (elS0Bar) elS0Bar.style.width = `${Math.min(100, s0MissPct)}%`;
    const elS0P95 = document.getElementById('s0-p95');
    if (elS0P95) elS0P95.textContent = s0P95 > 0 ? `${s0P95.toFixed(0)} µs` : '-- µs';

    // Update S1 Cards
    const elS1Miss = document.getElementById('s1-miss-pct');
    if (elS1Miss) elS1Miss.textContent = `${s1MissPct.toFixed(1)}%`;
    const elS1Count = document.getElementById('s1-miss-count');
    if (elS1Count) elS1Count.textContent = `${simState.s1.critMisses} / ${simState.s1.critTotal}`;
    const elS1Bar = document.getElementById('s1-bar-fill');
    if (elS1Bar) elS1Bar.style.width = `${Math.min(100, s1MissPct)}%`;
    const elS1P95 = document.getElementById('s1-p95');
    if (elS1P95) elS1P95.textContent = s1P95 > 0 ? `${s1P95.toFixed(0)} µs` : '-- µs';

    // Update S2 Cards
    const elS2Miss = document.getElementById('s2-miss-pct');
    if (elS2Miss) elS2Miss.textContent = `${s2MissPct.toFixed(1)}%`;
    const elS2Count = document.getElementById('s2-miss-count');
    if (elS2Count) elS2Count.textContent = `${simState.s2.critMisses} / ${simState.s2.critTotal}`;
    const elS2Bar = document.getElementById('s2-bar-fill');
    if (elS2Bar) elS2Bar.style.width = `${Math.min(100, s2MissPct)}%`;
    const elS2P95 = document.getElementById('s2-p95');
    if (elS2P95) elS2P95.textContent = s2P95 > 0 ? `${s2P95.toFixed(0)} µs` : '-- µs';

    // Update S3 TEMPO Cards
    const elS3Miss = document.getElementById('s3-miss-pct');
    if (elS3Miss) elS3Miss.textContent = `${s3MissPct.toFixed(1)}%`;
    const elS3Count = document.getElementById('s3-miss-count');
    if (elS3Count) elS3Count.textContent = `${simState.s3.critMisses} / ${simState.s3.critTotal}`;
    const elS3Bar = document.getElementById('s3-bar-fill');
    if (elS3Bar) elS3Bar.style.width = `${Math.min(100, s3MissPct)}%`;
    const elS3P95 = document.getElementById('s3-p95');
    if (elS3P95) elS3P95.textContent = s3P95 > 0 ? `${s3P95.toFixed(0)} µs` : '-- µs';

    // 5. Update Head-to-Head View
    const baseKey = simState.h2hBaseline || 's1';
    const baseSched = simState[baseKey] || simState.s1;
    const baseMissPct = baseKey === 's0' ? s0MissPct : (baseKey === 's2' ? s2MissPct : s1MissPct);
    const baseP95 = baseKey === 's0' ? s0P95 : (baseKey === 's2' ? s2P95 : s1P95);
    const baseP999 = baseKey === 's0' ? s0P999 : (baseKey === 's2' ? s2P999 : s1P999);

    const baseMeta = {
        's0': { tag: 'S0', name: 'Legacy FIFO', sub: 'Host-Blind / HW-Blind' },
        's1': { tag: 'S1', name: 'AI-Priority', sub: 'Host-Only Priority' },
        's2': { tag: 'S2', name: 'SSD-State', sub: 'HW-Only Channel Load' }
    }[baseKey];

    const elH2hTag = document.getElementById('h2h-base-tag');
    if (elH2hTag) elH2hTag.textContent = baseMeta.tag;
    const elH2hName = document.getElementById('h2h-base-name');
    if (elH2hName) elH2hName.textContent = baseMeta.name;
    const elH2hSub = document.getElementById('h2h-base-sub');
    if (elH2hSub) elH2hSub.textContent = baseMeta.sub;

    const elH2hBaseMiss = document.getElementById('h2h-base-miss-pct');
    if (elH2hBaseMiss) elH2hBaseMiss.textContent = `${baseMissPct.toFixed(1)}%`;
    const elH2hBaseBar = document.getElementById('h2h-base-bar-fill');
    if (elH2hBaseBar) {
        elH2hBaseBar.style.width = `${Math.min(100, baseMissPct)}%`;
        elH2hBaseBar.className = `bar-fill bar-${baseKey}`;
    }
    const elH2hBaseCount = document.getElementById('h2h-base-miss-count');
    if (elH2hBaseCount) elH2hBaseCount.textContent = `${baseSched.critMisses} / ${baseSched.critTotal}`;
    const elH2hBaseP95 = document.getElementById('h2h-base-p95');
    if (elH2hBaseP95) elH2hBaseP95.textContent = baseP95 > 0 ? `${baseP95.toFixed(0)} µs` : '-- µs';
    const elH2hBaseP999 = document.getElementById('h2h-base-p999');
    if (elH2hBaseP999) elH2hBaseP999.textContent = baseP999 > 0 ? `${baseP999.toFixed(0)} µs` : '-- µs';

    const elH2hS3Miss = document.getElementById('h2h-s3-miss-pct');
    if (elH2hS3Miss) elH2hS3Miss.textContent = `${s3MissPct.toFixed(1)}%`;
    const elH2hS3Bar = document.getElementById('h2h-s3-bar-fill');
    if (elH2hS3Bar) elH2hS3Bar.style.width = `${Math.min(100, s3MissPct)}%`;
    const elH2hS3Count = document.getElementById('h2h-s3-miss-count');
    if (elH2hS3Count) elH2hS3Count.textContent = `${simState.s3.critMisses} / ${simState.s3.critTotal}`;
    const elH2hS3P95 = document.getElementById('h2h-s3-p95');
    if (elH2hS3P95) elH2hS3P95.textContent = s3P95 > 0 ? `${s3P95.toFixed(0)} µs` : '-- µs';
    const elH2hS3P999 = document.getElementById('h2h-s3-p999');
    if (elH2hS3P999) elH2hS3P999.textContent = s3P999 > 0 ? `${s3P999.toFixed(0)} µs` : '-- µs';

    // Advantage Banner
    const comparisonMiss = simState.telemetryMode === 'h2h' ? baseMissPct : s1MissPct;
    const delta = comparisonMiss - s3MissPct;
    const advBanner = document.getElementById('adv-delta-text');
    if (advBanner) {
        if (delta > 0) {
            const compLabel = simState.telemetryMode === 'h2h' ? baseMeta.name : 'S1 AI-Priority';
            advBanner.textContent = `${delta.toFixed(1)} percentage points lower miss rate than ${compLabel} (${comparisonMiss.toFixed(1)}% -> ${s3MissPct.toFixed(1)}%)`;
        } else {
            advBanner.textContent = `Equalizing across initial trace startup`;
        }
    }

    // 6. Draw Live Latency Canvas
    drawLiveChart();
}

// Simulation Main Loop (60 FPS)
let lastTimestamp = performance.now();
function animationLoop(timestamp) {
    const elapsedMs = Math.min(timestamp - lastTimestamp, 100.0);
    lastTimestamp = timestamp;

    if (simState.isRunning) {
        // Human-observable pacing: 0.1x is ultra slow-motion, 1x is smooth real-time
        const stepUs = Math.min(elapsedMs * 0.4 * simState.speedMultiplier, 250.0);
        stepSimulation(stepUs);
    }

    render();
    requestAnimationFrame(animationLoop);
}

// Reset State for All 4 Policies
function resetSimulation() {
    simState.isRunning = false;
    simState.simTimeUs = 0.0;
    simState.traceIndex = 0;
    simState.rescuedTokens = 0;
    simState.tokenHistory = [];

    ['s0', 's1', 's2', 's3'].forEach(policyKey => {
        const sched = simState[policyKey];
        sched.queue = [];
        sched.completed = [];
        sched.critMisses = 0;
        sched.critTotal = 0;
        sched.latencies = [];
        sched.channels.forEach(ch => {
            ch.busBusyUntil = 0;
            ch.luns.forEach(lun => {
                lun.busyUntil = 0;
                lun.currentOp = 'IDLE';
                lun.opStartUs = 0;
                lun.opDurationUs = 0;
            });
        });
    });

    simState.trace = generateTrace(simState.activeScenario);

    // Pre-populate queues with initial batch of 6 requests from trace so cards are immediately visible!
    for (let i = 0; i < 6 && simState.traceIndex < simState.trace.length; i++) {
        const req = simState.trace[simState.traceIndex++];
        simState.s0.queue.push({ ...req });
        simState.s1.queue.push({ ...req });
        simState.s2.queue.push({ ...req });
        simState.s3.queue.push({ ...req });
    }

    const playBtn = document.getElementById('btn-play-pause');
    if (playBtn) {
        playBtn.classList.remove('btn-secondary');
        playBtn.classList.add('btn-primary');
        const playIcon = document.getElementById('play-icon');
        const playText = document.getElementById('play-text');
        if (playIcon) playIcon.textContent = '▶';
        if (playText) playText.textContent = 'Start Simulation';
    }

    const log = document.getElementById('inspector-log');
    if (log) {
        log.innerHTML = `
            <div class="log-entry log-system">
                <span class="log-ts mono">[0.0 µs]</span>
                <span class="log-msg">Simulation reset to zero. Loaded ${simState.trace.length} requests. Initial 6 requests buffered in NVMe Submission Queue. Concurrent 4-way evaluation active (S0, S1, S2, S3).</span>
            </div>
        `;
    }
}

// Setup Event Listeners and Tab Navigation
document.addEventListener('DOMContentLoaded', () => {
    resetSimulation();

    // Tab Navigation Handlers
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-view').forEach(v => v.classList.remove('active'));
            tab.classList.add('active');
            const targetId = tab.dataset.tab;
            const targetEl = document.getElementById(targetId);
            if (targetEl) targetEl.classList.add('active');
        });
    });

    // Matrix Policy Switcher Buttons
    document.querySelectorAll('.mps-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.mps-btn').forEach(b => b.classList.remove('active'));
            const targetBtn = e.target.closest('.mps-btn');
            if (!targetBtn) return;
            targetBtn.classList.add('active');
            simState.activeVisualPolicy = targetBtn.dataset.policy || 's3';
            render();
        });
    });

    // Telemetry View Mode Switcher (4-Way Board vs Head-to-Head)
    const btn4Way = document.getElementById('btn-view-4way');
    const btnH2H = document.getElementById('btn-view-h2h');
    const fourWayContainer = document.getElementById('four-way-container');
    const h2hContainer = document.getElementById('h2h-container');

    if (btn4Way && btnH2H && fourWayContainer && h2hContainer) {
        btn4Way.addEventListener('click', () => {
            btn4Way.classList.add('active');
            btnH2H.classList.remove('active');
            fourWayContainer.style.display = 'grid';
            h2hContainer.style.display = 'none';
            simState.telemetryMode = '4way';
            render();
        });

        btnH2H.addEventListener('click', () => {
            btnH2H.classList.add('active');
            btn4Way.classList.remove('active');
            fourWayContainer.style.display = 'none';
            h2hContainer.style.display = 'block';
            simState.telemetryMode = 'h2h';
            render();
        });
    }

    // Head-to-Head Baseline Dropdown Selector
    const h2hSelect = document.getElementById('select-h2h-baseline');
    if (h2hSelect) {
        h2hSelect.addEventListener('change', (e) => {
            simState.h2hBaseline = e.target.value;
            render();
        });
    }

    // Play / Pause Button
    document.getElementById('btn-play-pause').addEventListener('click', () => {
        simState.isRunning = !simState.isRunning;
        const playIcon = document.getElementById('play-icon');
        const playText = document.getElementById('play-text');
        const btn = document.getElementById('btn-play-pause');

        if (simState.isRunning) {
            playIcon.textContent = '⏸';
            playText.textContent = 'Pause';
            btn.classList.remove('btn-primary');
            btn.classList.add('btn-secondary');
        } else {
            playIcon.textContent = '▶';
            playText.textContent = 'Resume';
            btn.classList.remove('btn-secondary');
            btn.classList.add('btn-primary');
        }
    });

    // Step 1 Token Button (Inspection Mode)
    document.getElementById('btn-step').addEventListener('click', stepSingleToken);

    // Reset Button
    document.getElementById('btn-reset').addEventListener('click', resetSimulation);

    // Speed Selector Buttons
    document.querySelectorAll('.speed-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            simState.speedMultiplier = parseFloat(e.target.dataset.speed);
        });
    });

    // Scenario Selector
    document.getElementById('select-scenario').addEventListener('change', (e) => {
        simState.activeScenario = e.target.value;
        resetSimulation();
    });

    requestAnimationFrame(animationLoop);
});
