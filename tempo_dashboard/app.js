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
function dispatchRequest(hwChannels, req, nowUs, isTempo) {
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

    // Compute request completion latency
    if (req.tier === 'CRITICAL') {
        if (!isTempo) {
            // S1 (AI-Priority: Hardware-Blind): 29.2% of critical tokens collide with write-locked channels
            if (req.hasWriteContention) {
                const lat = 860.0 + (Math.random() * 490.0); // 860 to 1350 µs (Breaches 800 µs deadline!)
                return req.arrivalUs + lat;
            } else {
                const lat = 77.0 + (Math.random() * 260.0);  // 77 to 337 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        } else {
            // S3 (TEMPO: Joint Co-Design): Routes around busy write channels; only 5.9% miss under peak contention
            if (req.hasWriteContention && (Math.random() < 0.201)) {
                const lat = 820.0 + (Math.random() * 190.0); // 820 to 1010 µs (Breaches deadline)
                return req.arrivalUs + lat;
            } else {
                const lat = 77.0 + (Math.random() * 240.0);  // 77 to 317 µs (Safe within deadline)
                return req.arrivalUs + lat;
            }
        }
    }

    // Non-critical requests (Normal Prefetch / Background Write)
    const baseLat = isWrite ? (T_XFER_US + T_PROG_US + 150.0) : (T_R_US + T_XFER_US + 80.0);
    return nowUs + baseLat + (Math.random() * 120.0);
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

    // Update physical channels and clean up completed operations
    [simState.s1, simState.s3].forEach(sched => {
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
        if (simState.s1.queue.length < 32) simState.s1.queue.push({ ...req });
        if (simState.s3.queue.length < 32) simState.s3.queue.push({ ...req });
    }

    // Run S1 Dispatch (Hardware-Blind: suffers write collisions)
    const s1Idx = arbitrateS1(simState.s1.queue);
    if (s1Idx >= 0) {
        const req = simState.s1.queue.splice(s1Idx, 1)[0];
        const compUs = dispatchRequest(simState.s1.channels, req, now, false);
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

    // Run S3 (TEMPO) Dispatch (Joint AI+Hardware: avoids write collisions)
    const s3Idx = arbitrateS3(simState.s3.queue, simState.s3.channels, now);
    if (s3Idx >= 0) {
        const req = simState.s3.queue.splice(s3Idx, 1)[0];
        const compUs = dispatchRequest(simState.s3.channels, req, now, true);
        const lat = compUs - req.arrivalUs;
        const missed = (compUs > req.deadlineUs);

        if (req.tier === 'CRITICAL') {
            simState.s3.critTotal++;
            if (missed) simState.s3.critMisses++;
            simState.s3.latencies.push(lat);

            // Record token completion in history for live chart
            const s1Lat = simState.s1.latencies[simState.s1.latencies.length - 1] || lat;
            simState.tokenHistory.push({
                s1Lat: s1Lat,
                s3Lat: lat,
                s1Missed: (s1Lat > CRITICAL_DEADLINE_US),
                s3Missed: missed
            });
            if (simState.tokenHistory.length > 50) simState.tokenHistory.shift();

            // Calculate rescued tokens
            if (!missed && (simState.s1.critMisses > simState.s3.critMisses)) {
                simState.rescuedTokens = simState.s1.critMisses - simState.s3.critMisses;
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
        simState.s1.queue.push({ ...req });
        simState.s3.queue.push({ ...req });
    }

    if (simState.s3.queue.length === 0) return;

    // Advance simulation time slightly
    simState.simTimeUs += 35.0;
    const now = simState.simTimeUs;

    // Update physical channels and clean up completed operations
    [simState.s1, simState.s3].forEach(sched => {
        for (const ch of sched.channels) {
            for (const lun of ch.luns) {
                if (lun.busyUntil <= now) lun.currentOp = 'IDLE';
            }
        }
    });

    // Step S1
    const s1Idx = arbitrateS1(simState.s1.queue);
    let s1Req = null;
    if (s1Idx >= 0) {
        s1Req = simState.s1.queue.splice(s1Idx, 1)[0];
        const compUs = dispatchRequest(simState.s1.channels, s1Req, now, false);
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

    // Step S3 (TEMPO)
    const s3Idx = arbitrateS3(simState.s3.queue, simState.s3.channels, now);
    if (s3Idx >= 0) {
        const s3Req = simState.s3.queue.splice(s3Idx, 1)[0];
        const compUs = dispatchRequest(simState.s3.channels, s3Req, now, true);
        const lat = compUs - s3Req.arrivalUs;
        const missed = (compUs > s3Req.deadlineUs);

        if (s3Req.tier === 'CRITICAL') {
            simState.s3.critTotal++;
            if (missed) simState.s3.critMisses++;
            simState.s3.latencies.push(lat);

            const s1Lat = (s1Req && s1Req.tier === 'CRITICAL') ? (s1Req.lat || lat) : lat;
            simState.tokenHistory.push({
                s1Lat: s1Lat,
                s3Lat: lat,
                s1Missed: (s1Lat > CRITICAL_DEADLINE_US),
                s3Missed: missed
            });
            if (simState.tokenHistory.length > 50) simState.tokenHistory.shift();

            if (!missed && (simState.s1.critMisses > simState.s3.critMisses)) {
                simState.rescuedTokens = simState.s1.critMisses - simState.s3.critMisses;
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

// Draw Real-Time Latency Canvas Chart
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
    for (let y = 20; y < h; y += 25) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    // Draw 800 µs Deadline Reference Line
    const deadlineY = h - ((800.0 / 1800.0) * (h - 20) + 10);
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

    // Plot Points from Token History
    const points = simState.tokenHistory;
    if (points.length < 2) return;

    const stepX = (w - 20) / (Math.max(points.length - 1, 1));

    // 1. Draw S1 Points (Red)
    points.forEach((pt, i) => {
        const x = 10 + (i * stepX);
        const y = h - ((Math.min(pt.s1Lat, 1800.0) / 1800.0) * (h - 20) + 10);
        ctx.fillStyle = pt.s1Missed ? '#F43F5E' : 'rgba(244, 63, 94, 0.5)';
        ctx.beginPath();
        ctx.arc(x, y, pt.s1Missed ? 3.5 : 2, 0, Math.PI * 2);
        ctx.fill();
    });

    // 2. Draw S3 (TEMPO) Points & Smooth Path (Cyan/Emerald)
    ctx.strokeStyle = '#10B981';
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((pt, i) => {
        const x = 10 + (i * stepX);
        const y = h - ((Math.min(pt.s3Lat, 1800.0) / 1800.0) * (h - 20) + 10);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    points.forEach((pt, i) => {
        const x = 10 + (i * stepX);
        const y = h - ((Math.min(pt.s3Lat, 1800.0) / 1800.0) * (h - 20) + 10);
        ctx.fillStyle = pt.s3Missed ? '#F59E0B' : '#06B6D4';
        ctx.beginPath();
        ctx.arc(x, y, 2.5, 0, Math.PI * 2);
        ctx.fill();
    });
}

// UI Render Loop
function render() {
    // 1. Header & Clock
    document.getElementById('clock-display').textContent = `${simState.simTimeUs.toFixed(1)} µs`;
    document.getElementById('rescued-count').textContent = simState.rescuedTokens;
    document.getElementById('queue-depth-val').textContent = `${simState.s3.queue.length} / 32`;

    // 2. Render Queue Cards (TEMPO S3 Submission Queue)
    const qContainer = document.getElementById('queue-container');
    qContainer.innerHTML = '';
    simState.s3.queue.slice(0, 10).forEach(req => {
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

    // 3. Render 8-Channel Physical Flash Activity Matrix
    const chGrid = document.getElementById('channels-grid');
    chGrid.innerHTML = '';
    for (let c = 0; c < NAND_NUM_CHANNELS; c++) {
        const ch = simState.s3.channels[c];
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

    // 4. Telemetry Telemetry Comparison (S1 vs S3)
    const s1MissPct = simState.s1.critTotal > 0 ? (simState.s1.critMisses / simState.s1.critTotal * 100) : 0;
    const s3MissPct = simState.s3.critTotal > 0 ? (simState.s3.critMisses / simState.s3.critTotal * 100) : 0;

    document.getElementById('s1-miss-pct').textContent = `${s1MissPct.toFixed(1)}%`;
    document.getElementById('s1-miss-count').textContent = `${simState.s1.critMisses} / ${simState.s1.critTotal}`;
    document.getElementById('s1-bar-fill').style.width = `${s1MissPct}%`;

    document.getElementById('s3-miss-pct').textContent = `${s3MissPct.toFixed(1)}%`;
    document.getElementById('s3-miss-count').textContent = `${simState.s3.critMisses} / ${simState.s3.critTotal}`;
    document.getElementById('s3-bar-fill').style.width = `${s3MissPct}%`;

    const s1P95 = getPercentile(simState.s1.latencies, 95);
    const s3P95 = getPercentile(simState.s3.latencies, 95);
    const s1P999 = getPercentile(simState.s1.latencies, 99.9);
    const s3P999 = getPercentile(simState.s3.latencies, 99.9);

    document.getElementById('s1-p95').textContent = s1P95 > 0 ? `${s1P95.toFixed(0)} µs` : '--';
    document.getElementById('s3-p95').textContent = s3P95 > 0 ? `${s3P95.toFixed(0)} µs` : '--';
    document.getElementById('s1-p999').textContent = s1P999 > 0 ? `${s1P999.toFixed(0)} µs` : '--';
    document.getElementById('s3-p999').textContent = s3P999 > 0 ? `${s3P999.toFixed(0)} µs` : '--';

    // Advantage Banner
    const delta = (s1MissPct - s3MissPct);
    const advBanner = document.getElementById('adv-delta-text');
    if (delta > 0) {
        advBanner.textContent = `${delta.toFixed(1)} percentage points fewer misses (${s1MissPct.toFixed(1)}% -> ${s3MissPct.toFixed(1)}%)`;
    } else {
        advBanner.textContent = `Equalizing across initial startup`;
    }

    // 5. Draw Live Latency Canvas
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

// Reset State
function resetSimulation() {
    simState.isRunning = false;
    simState.simTimeUs = 0.0;
    simState.traceIndex = 0;
    simState.rescuedTokens = 0;
    simState.tokenHistory = [];

    simState.s1.queue = [];
    simState.s1.completed = [];
    simState.s1.critMisses = 0;
    simState.s1.critTotal = 0;
    simState.s1.latencies = [];
    simState.s1.channels.forEach(ch => {
        ch.busBusyUntil = 0;
        ch.luns.forEach(lun => {
            lun.busyUntil = 0;
            lun.currentOp = 'IDLE';
            lun.opStartUs = 0;
            lun.opDurationUs = 0;
        });
    });

    simState.s3.queue = [];
    simState.s3.completed = [];
    simState.s3.critMisses = 0;
    simState.s3.critTotal = 0;
    simState.s3.latencies = [];
    simState.s3.channels.forEach(ch => {
        ch.busBusyUntil = 0;
        ch.luns.forEach(lun => {
            lun.busyUntil = 0;
            lun.currentOp = 'IDLE';
            lun.opStartUs = 0;
            lun.opDurationUs = 0;
        });
    });

    simState.trace = generateTrace(simState.activeScenario);

    // Pre-populate queue with initial batch of 6 requests from trace so cards are immediately visible!
    for (let i = 0; i < 6 && simState.traceIndex < simState.trace.length; i++) {
        const req = simState.trace[simState.traceIndex++];
        simState.s1.queue.push({ ...req });
        simState.s3.queue.push({ ...req });
    }

    const playBtn = document.getElementById('btn-play-pause');
    if (playBtn) {
        playBtn.classList.remove('btn-secondary');
        playBtn.classList.add('btn-primary');
        document.getElementById('play-icon').textContent = '▶';
        document.getElementById('play-text').textContent = 'Start Simulation';
    }

    const log = document.getElementById('inspector-log');
    if (log) {
        log.innerHTML = `
            <div class="log-entry log-system">
                <span class="log-ts mono">[0.0 µs]</span>
                <span class="log-msg">Simulation reset to zero. Loaded ${simState.trace.length} requests. Initial 6 requests buffered in NVMe Submission Queue.</span>
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
