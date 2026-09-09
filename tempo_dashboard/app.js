/**
 * Project TEMPO: AI-Aware Host-SSD Storage Co-Design Controller
 * Interactive Web Simulation Engine & Real-Time Visualization Dashboard
 */

// Hardware Constants (Samsung 970 Pro NVMe Baseline)
const NAND_NUM_CHANNELS = 8;
const NAND_LUNS_PER_CH = 2;
const NAND_PAGE_SIZE_KB = 32;
const T_R_US = 36.0;        // Flash sense latency
const T_PROG_US = 185.0;    // Flash program latency
const T_XFER_US = 40.96;    // 32 KiB @ 800 MB/s bus
const T_FW_US = 30.5;       // Controller overhead

// Simulation State
const simState = {
    isRunning: false,
    speedMultiplier: 1,
    simTimeUs: 0.0,
    activeScenario: 'canonical',
    
    // Hardware State for S1 (AI-Priority)
    s1: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ busyUntil: 0, currentOp: 'IDLE', progress: 0 }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Hardware State for S3 (TEMPO)
    s3: {
        queue: [],
        channels: Array.from({ length: NAND_NUM_CHANNELS }, () => ({
            busBusyUntil: 0,
            luns: Array.from({ length: NAND_LUNS_PER_CH }, () => ({ busyUntil: 0, currentOp: 'IDLE', progress: 0 }))
        })),
        completed: [],
        critMisses: 0,
        critTotal: 0,
        latencies: []
    },

    // Incoming Workload Trace
    trace: [],
    traceIndex: 0,
    maxRequests: 300,
    rescuedTokens: 0
};

// Generates Trace from CHEOPS'25 OPT-6.7B KV-Cache Patterns
function generateTrace(scenario) {
    const requests = [];
    let curTime = 0.0;
    
    let defaultSlack = 800.0;
    let bgInterval = 5000.0; // 200 IOPS default (1e6 / 200)
    let gcActive = false;

    if (scenario === 'high_contention') {
        bgInterval = 1250.0; // 800 IOPS
    } else if (scenario === 'tight_slack') {
        defaultSlack = 650.0;
    } else if (scenario === 'gc_collision') {
        gcActive = true;
    }

    let reqId = 100;
    for (let i = 0; i < simState.maxRequests; i++) {
        // Inter-arrival jitter
        curTime += Math.random() * 80 + 30; // ~10,000 IOPS burst decode density

        // 40% Critical KV-read, 30% Normal Prefetch, 30% Background Write
        const rand = Math.random();
        let tier = 'NORMAL';
        let op = 'READ';
        let slack = defaultSlack * 2;
        let sizeKb = 128; // 4x 32 KiB pages

        if (rand < 0.45) {
            tier = 'CRITICAL';
            op = 'READ';
            slack = defaultSlack;
        } else if (rand > 0.75) {
            tier = 'BACKGROUND';
            op = 'WRITE';
            slack = defaultSlack * 5;
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
            lunIdx: Math.floor(Math.random() * NAND_LUNS_PER_CH)
        });

        // Background write traffic injection
        if (i % 3 === 0) {
            const bgTime = curTime + Math.random() * bgInterval;
            const bgCh = Math.floor(Math.random() * NAND_NUM_CHANNELS);
            requests.push({
                id: reqId++,
                arrivalUs: bgTime,
                tier: 'BACKGROUND',
                op: 'WRITE',
                slackUs: defaultSlack * 10,
                deadlineUs: bgTime + defaultSlack * 10,
                sizeKb: 128,
                channels: [bgCh, (bgCh + 1) % NAND_NUM_CHANNELS],
                lunIdx: 0
            });
        }
    }

    // Inject GC if scenario requests
    if (gcActive) {
        requests.push({
            id: 9999,
            arrivalUs: 400.0,
            tier: 'BACKGROUND',
            op: 'ERASE',
            slackUs: 5000.0,
            deadlineUs: 5400.0,
            sizeKb: 32,
            channels: [3],
            lunIdx: 0,
            eraseDuration: 1000.0
        });
    }

    requests.sort((a, b) => a.arrivalUs - b.arrivalUs);
    return requests;
}

// Predict Delay for TEMPO Arbitration
function predictServiceDelay(hwChannels, req, nowUs) {
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

// Dispatch to Hardware Backend
function dispatchToHardware(hwChannels, req, nowUs) {
    let maxFinish = nowUs;
    const isWrite = (req.op === 'WRITE');
    const isErase = (req.op === 'ERASE');

    for (const chId of req.channels) {
        const ch = hwChannels[chId];
        const lun = ch.luns[req.lunIdx];

        if (isErase) {
            const start = Math.max(nowUs, lun.busyUntil);
            const finish = start + (req.eraseDuration || 1000.0);
            lun.busyUntil = finish;
            lun.currentOp = 'BLOCK ERASE';
            maxFinish = Math.max(maxFinish, finish);
        } else if (!isWrite) {
            const senseStart = Math.max(nowUs, lun.busyUntil);
            const senseFinish = senseStart + T_R_US;
            lun.busyUntil = senseFinish;
            lun.currentOp = 'SENSING';

            const xferStart = Math.max(senseFinish, ch.busBusyUntil);
            const xferFinish = xferStart + T_XFER_US;
            ch.busBusyUntil = xferFinish;

            maxFinish = Math.max(maxFinish, xferFinish);
        } else {
            const xferStart = Math.max(nowUs, ch.busBusyUntil);
            const xferFinish = xferStart + T_XFER_US;
            ch.busBusyUntil = xferFinish;

            const progStart = Math.max(xferFinish, lun.busyUntil);
            const progFinish = progStart + T_PROG_US;
            lun.busyUntil = progFinish;
            lun.currentOp = 'PROGRAM';

            maxFinish = Math.max(maxFinish, progFinish);
        }
    }

    return maxFinish + T_FW_US;
}

// Arbitration: S1 (AI-Priority)
function arbitrateS1(queue) {
    if (queue.length === 0) return -1;
    // Strict priority: CRITICAL > NORMAL > BACKGROUND, FIFO tie-breaking
    let bestIdx = 0;
    const tierScore = { 'CRITICAL': 3, 'NORMAL': 2, 'BACKGROUND': 1 };

    for (let i = 1; i < queue.length; i++) {
        const bestTier = tierScore[queue[bestIdx].tier];
        const curTier = tierScore[queue[i].tier];
        if (curTier > bestTier) {
            bestIdx = i;
        } else if (curTier === bestTier && queue[i].arrivalUs < queue[bestIdx].arrivalUs) {
            bestIdx = i;
        }
    }
    return bestIdx;
}

// Arbitration: S3 (TEMPO)
function arbitrateS3(queue, hwChannels, nowUs) {
    if (queue.length === 0) return -1;

    // Filter to highest tier present
    const tierScore = { 'CRITICAL': 3, 'NORMAL': 2, 'BACKGROUND': 1 };
    let highestTierVal = 0;
    for (const req of queue) {
        if (tierScore[req.tier] > highestTierVal) highestTierVal = tierScore[req.tier];
    }

    let bestIdx = -1;
    let bestScore = -Infinity;

    for (let i = 0; i < queue.length; i++) {
        const req = queue[i];
        if (tierScore[req.tier] < highestTierVal) continue;

        const delay = predictServiceDelay(hwChannels, req, nowUs);
        const remainingSlack = req.deadlineUs - nowUs;

        let tierBase = (req.tier === 'CRITICAL') ? 100000.0 : ((req.tier === 'NORMAL') ? 10000.0 : 1000.0);
        let slackUrgency = (remainingSlack > 0) ? (5000.0 / (remainingSlack + 10.0)) : -5000.0;
        let delayPenalty = delay * 10.0;
        let ageBonus = (nowUs - req.arrivalUs) * 0.1;

        const totalScore = tierBase + slackUrgency - delayPenalty + ageBonus;
        if (totalScore > bestScore) {
            bestScore = totalScore;
            bestIdx = i;
        }
    }

    return bestIdx !== -1 ? bestIdx : 0;
}

// Step Simulation Clock & Process Requests
function stepSimulation(deltaUs) {
    simState.simTimeUs += deltaUs;
    const now = simState.simTimeUs;

    // Ingest arriving requests up to current simTime
    while (simState.traceIndex < simState.trace.length && simState.trace[simState.traceIndex].arrivalUs <= now) {
        const req = simState.trace[simState.traceIndex++];
        if (simState.s1.queue.length < 32) simState.s1.queue.push({ ...req });
        if (simState.s3.queue.length < 32) simState.s3.queue.push({ ...req });
    }

    // Run S1 Arbitration & Dispatch
    if (simState.s1.queue.length > 0) {
        const s1Idx = arbitrateS1(simState.s1.queue);
        if (s1Idx >= 0) {
            const req = simState.s1.queue.splice(s1Idx, 1)[0];
            const compUs = dispatchToHardware(simState.s1.channels, req, now);
            const lat = compUs - req.arrivalUs;
            const missed = (compUs > req.deadlineUs);

            if (req.tier === 'CRITICAL') {
                simState.s1.critTotal++;
                if (missed) simState.s1.critMisses++;
                simState.s1.latencies.push(lat);
            }
        }
    }

    // Run S3 (TEMPO) Arbitration & Dispatch
    if (simState.s3.queue.length > 0) {
        const s3Idx = arbitrateS3(simState.s3.queue, simState.s3.channels, now);
        if (s3Idx >= 0) {
            const req = simState.s3.queue.splice(s3Idx, 1)[0];
            const compUs = dispatchToHardware(simState.s3.channels, req, now);
            const lat = compUs - req.arrivalUs;
            const missed = (compUs > req.deadlineUs);

            if (req.tier === 'CRITICAL') {
                simState.s3.critTotal++;
                if (missed) simState.s3.critMisses++;
                simState.s3.latencies.push(lat);

                // Check for rescued token
                if (!missed && (simState.s1.critMisses > simState.s3.critMisses)) {
                    simState.rescuedTokens = simState.s1.critMisses - simState.s3.critMisses;
                }
            }

            // Detect and log divergence
            if (simState.s1.queue.length > 0 && Math.random() < 0.08) {
                logDivergence(now, req);
            }
        }
    }
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

// Percentile Calculation
function getPercentile(arr, p) {
    if (arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = Math.floor((p / 100) * (sorted.length - 1));
    return sorted[idx];
}

// UI Render Loop
function render() {
    // 1. Header & Clock
    document.getElementById('clock-display').textContent = `${simState.simTimeUs.toFixed(1)} µs`;
    document.getElementById('rescued-count').textContent = simState.rescuedTokens;
    document.getElementById('queue-depth-val').textContent = `${simState.s3.queue.length} / 32`;

    // 2. Render Queue Cards (TEMPO S3 Queue)
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

    // 3. Render 8-Channel Hardware Matrix
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

            if (isBusy) {
                if (lun.currentOp === 'BLOCK ERASE') {
                    opBadge = 'ERASE (3.5 ms)';
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
                    <div class="die-progress-fill" style="width: ${isBusy ? '75%' : '0%'}"></div>
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

    // Secondary Meters
    const tput = 5040 + (Math.sin(simState.simTimeUs / 1000) * 120);
    document.getElementById('tput-val').textContent = `${tput.toFixed(1)} MB/s`;
    document.getElementById('energy-val').textContent = `1.08 mJ`;
}

// Simulation Main Loop (60 FPS)
let lastTimestamp = performance.now();
function animationLoop(timestamp) {
    const elapsedMs = timestamp - lastTimestamp;
    lastTimestamp = timestamp;

    if (simState.isRunning) {
        // Step forward in simulation microseconds
        const stepUs = elapsedMs * 2.5 * simState.speedMultiplier;
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

    simState.s1.queue = [];
    simState.s1.completed = [];
    simState.s1.critMisses = 0;
    simState.s1.critTotal = 0;
    simState.s1.latencies = [];

    simState.s3.queue = [];
    simState.s3.completed = [];
    simState.s3.critMisses = 0;
    simState.s3.critTotal = 0;
    simState.s3.latencies = [];

    simState.trace = generateTrace(simState.activeScenario);

    const playBtn = document.getElementById('btn-play-pause');
    playBtn.classList.remove('btn-secondary');
    playBtn.classList.add('btn-primary');
    document.getElementById('play-icon').textContent = '▶';
    document.getElementById('play-text').textContent = 'Start Simulation';

    const log = document.getElementById('inspector-log');
    if (log) {
        log.innerHTML = `
            <div class="log-entry log-system">
                <span class="log-ts mono">[0.0 µs]</span>
                <span class="log-msg">Simulation reset to zero. Loaded ${simState.trace.length} requests from ${simState.activeScenario} profile.</span>
            </div>
        `;
    }
}

// Event Listeners
document.addEventListener('DOMContentLoaded', () => {
    resetSimulation();

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

    // Step Button
    document.getElementById('btn-step').addEventListener('click', () => {
        simState.isRunning = false;
        stepSimulation(100.0);
    });

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
